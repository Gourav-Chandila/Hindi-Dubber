package com.hindidub.app.ui

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.hindidub.app.data.Api
import com.hindidub.app.data.Prefs
import com.hindidub.app.work.DubWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PickedVideo(val uri: Uri, val name: String, val size: Long)

sealed interface DubState {
    data object Idle : DubState
    data class Running(
        val stage: String, val label: String, val progress: Float,
        val etaSeconds: Long?, val jobId: String?, val speakers: Int?,
    ) : DubState
    data class Done(val uri: Uri, val name: String) : DubState
    data class Failed(val message: String) : DubState
}

data class ServerCheck(val checking: Boolean = false, val message: String? = null, val ok: Boolean? = null)

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = Prefs(app)
    private val wm = WorkManager.getInstance(app)

    private val _picked = MutableStateFlow<PickedVideo?>(null)
    val picked: StateFlow<PickedVideo?> = _picked.asStateFlow()

    private val _server = MutableStateFlow(prefs.serverUrl)
    val server: StateFlow<String> = _server.asStateFlow()
    private val _apiKey = MutableStateFlow(prefs.apiKey)
    val apiKey: StateFlow<String> = _apiKey.asStateFlow()
    private val _check = MutableStateFlow(ServerCheck())
    val check: StateFlow<ServerCheck> = _check.asStateFlow()

    val state: StateFlow<DubState> = wm.getWorkInfosForUniqueWorkFlow(DubWorker.UNIQUE)
        .map { infos -> toState(infos.firstOrNull()) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, lastResultOrIdle())

    private fun lastResultOrIdle(): DubState {
        val u = prefs.lastResultUri ?: return DubState.Idle
        return DubState.Done(Uri.parse(u), prefs.lastResultName ?: "Hindi video")
    }

    private fun toState(info: WorkInfo?): DubState {
        if (info == null) return lastResultOrIdle()
        return when (info.state) {
            WorkInfo.State.ENQUEUED, WorkInfo.State.RUNNING, WorkInfo.State.BLOCKED -> {
                val p = info.progress
                val stage = p.getString(DubWorker.KEY_STAGE) ?: "connect"
                DubState.Running(
                    stage = stage,
                    label = p.getString(DubWorker.KEY_LABEL)
                        ?: if (info.state == WorkInfo.State.ENQUEUED) "Waiting for network…" else "Starting…",
                    progress = p.getFloat(DubWorker.KEY_PROGRESS, 0f),
                    etaSeconds = p.getLong(DubWorker.KEY_ETA, -1L).takeIf { it >= 0 },
                    jobId = p.getString(DubWorker.KEY_JOB),
                    speakers = p.getInt(DubWorker.KEY_SPEAKERS, -1).takeIf { it >= 0 },
                )
            }
            WorkInfo.State.SUCCEEDED -> {
                val u = info.outputData.getString(DubWorker.KEY_RESULT)
                if (u != null) DubState.Done(Uri.parse(u), info.outputData.getString(DubWorker.KEY_NAME) ?: "")
                else lastResultOrIdle()
            }
            WorkInfo.State.FAILED ->
                DubState.Failed(info.outputData.getString(DubWorker.KEY_ERROR) ?: "Something went wrong.")
            WorkInfo.State.CANCELLED -> lastResultOrIdle()
        }
    }

    fun onVideoPicked(uri: Uri, persist: Boolean) {
        val ctx = getApplication<Application>()
        if (persist) {
            runCatching {
                ctx.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
        }
        var name = "video.mp4"
        var size = -1L
        runCatching {
            ctx.contentResolver.query(uri, null, null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val si = c.getColumnIndex(OpenableColumns.SIZE)
                    if (ni >= 0) name = c.getString(ni) ?: name
                    if (si >= 0 && !c.isNull(si)) size = c.getLong(si)
                }
            }
        }
        _picked.value = PickedVideo(uri, name, size)
    }

    fun setServer(url: String) { _server.value = url; prefs.serverUrl = url; _check.value = ServerCheck() }
    fun setApiKey(key: String) { _apiKey.value = key; prefs.apiKey = key }

    fun testServer() {
        _check.value = ServerCheck(checking = true, message = "Connecting… (a sleeping free server can take a minute)")
        viewModelScope.launch(Dispatchers.IO) {
            val result = runCatching { Api(prefs.serverUrl, prefs.apiKey).health() }
            _check.update {
                result.fold(
                    { ServerCheck(ok = true, message = "Connected ✓ (${it.optString("device", "cpu")})") },
                    { ServerCheck(ok = false, message = "Cannot reach server: ${it.message}") },
                )
            }
        }
    }

    fun startDub() {
        val v = _picked.value ?: return
        prefs.lastResultUri = null
        DubWorker.enqueue(getApplication<Application>(), v.uri, v.name, v.size)
    }

    fun cancel() {
        val jobId = (state.value as? DubState.Running)?.jobId
        wm.cancelUniqueWork(DubWorker.UNIQUE)
        if (jobId != null) viewModelScope.launch(Dispatchers.IO) { Api(prefs.serverUrl, prefs.apiKey).cancel(jobId) }
    }

    fun reset() {
        prefs.lastResultUri = null
        wm.pruneWork()
        _picked.value = null
    }
}
