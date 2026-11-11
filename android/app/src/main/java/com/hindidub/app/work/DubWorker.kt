package com.hindidub.app.work

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.PendingIntent
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.hindidub.app.HindiDubApp
import com.hindidub.app.MainActivity
import com.hindidub.app.R
import com.hindidub.app.data.Api
import com.hindidub.app.data.ApiException
import com.hindidub.app.data.Prefs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Whole dub in one resumable background job:
 *   1. chunked upload (resumes from the server's byte count after any failure)
 *   2. poll the server job until done
 *   3. download the Hindi video into Movies/HindiDub
 * Survives app close, network loss and reboots (WorkManager retries with backoff).
 */
class DubWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    private val prefs = Prefs(ctx)
    private val workKey = id.toString()
    private val notifId = 4242

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val uri = Uri.parse(inputData.getString(KEY_URI) ?: return@withContext Result.failure())
        val name = inputData.getString(KEY_NAME) ?: "video.mp4"
        val size = inputData.getLong(KEY_SIZE, -1L)
        val api = Api(prefs.serverUrl, prefs.apiKey)

        try {
            report(STAGE_CONNECT, 0f, "Waking up the server…")
            api.health()

            var jobId = prefs.jobId(workKey)
            if (jobId == null) {
                jobId = upload(api, uri, name, size)
                prefs.setJobId(workKey, jobId)
                prefs.setUploadId(workKey, null)
            }

            // ---- wait for the server ----
            while (true) {
                val st = api.job(jobId)
                when (st.status) {
                    "done" -> break
                    "failed" -> return@withContext fail(st.error ?: "Dubbing failed on the server.")
                    "cancelled" -> return@withContext fail("Cancelled.")
                }
                val label = if (st.status == "queued" && st.queuePosition > 0)
                    "Waiting in queue (#${st.queuePosition})" else stageLabel(st.stage)
                report(STAGE_SERVER, st.progress, label, st.etaSeconds, jobId, st.speakers)
                delay(if (st.status == "queued") 10_000 else 5_000)
            }

            // ---- download ----
            report(STAGE_DOWNLOAD, 0f, "Downloading Hindi video…", jobId = jobId)
            val outName = "HindiDub_" + name.substringBeforeLast('.') + ".mp4"
            val outUri = download(api, jobId, outName)
            prefs.lastResultUri = outUri.toString()
            prefs.lastResultName = outName
            prefs.clearWork(workKey)
            api.cancel(jobId) // frees server disk (job is finished, so this deletes it)
            notifyDone(outName)
            Result.success(workDataOf(KEY_RESULT to outUri.toString(), KEY_NAME to outName))
        } catch (e: SecurityException) {
            fail("Lost permission to read the video. Please pick it again.")
        } catch (e: ApiException) {
            if (e.code in listOf(400, 401, 413)) fail(e.message ?: "Server error")
            else if (e.code == 404 && prefs.jobId(workKey) != null) {
                prefs.clearWork(workKey); fail("Server restarted and lost this job. Please try again.")
            } else retryOrFail(e)
        } catch (e: IOException) {
            retryOrFail(e)
        }
    }

    private fun retryOrFail(e: Exception): Result =
        if (runAttemptCount < MAX_ATTEMPTS) {
            val msg = if (e is ApiException && e.code == 503) "Server offline – waiting for it to start…"
            else "Connection problem – retrying automatically…"
            setProgressAsyncSafe(STAGE_RETRY, 0f, msg)
            Result.retry()
        } else fail("Could not reach the server: ${e.message}")

    private fun fail(msg: String): Result {
        notify(msg, null, done = true)
        return Result.failure(workDataOf(KEY_ERROR to msg))
    }

    private suspend fun upload(api: Api, uri: Uri, name: String, knownSize: Long): String {
        val cr = applicationContext.contentResolver
        val size = if (knownSize > 0) knownSize else cr.openAssetFileDescriptor(uri, "r")!!.use { it.length }
        val saved: String? = prefs.uploadId(workKey)
        val resumeAt: Long? = saved?.let { sid -> runCatching { api.uploadReceived(sid) }.getOrNull() }
        val id: String
        var offset: Long
        if (saved != null && resumeAt != null) {
            id = saved
            offset = resumeAt
        } else {
            id = api.createUpload(name, size)
            prefs.setUploadId(workKey, id)
            offset = 0L
        }
        val buf = ByteArray(CHUNK)
        cr.openInputStream(uri)!!.use { input ->
            var skipped = 0L
            while (skipped < offset) {
                val s = input.skip(offset - skipped)
                if (s <= 0) throw IOException("Could not seek in video file")
                skipped += s
            }
            while (offset < size) {
                var len = 0
                while (len < CHUNK) {
                    val n = input.read(buf, len, CHUNK - len)
                    if (n < 0) break
                    len += n
                }
                if (len == 0) break
                val newOffset = api.putChunk(id, offset, buf, len)
                if (newOffset != offset + len) {
                    // Server and app disagree (e.g. a retried chunk); restart from server's count.
                    return upload(api, uri, name, size)
                }
                offset = newOffset
                report(STAGE_UPLOAD, offset.toFloat() / size, "Uploading ${percent(offset, size)}")
            }
        }
        return api.completeUpload(id)
    }

    private suspend fun download(api: Api, jobId: String, outName: String): Uri {
        val cr = applicationContext.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, outName)
            put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
            put(MediaStore.Video.Media.RELATIVE_PATH, Environment.DIRECTORY_MOVIES + "/HindiDub")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val target = cr.insert(MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), values)
            ?: throw IOException("Cannot create file in Movies")
        try {
            var last = 0L
            cr.openOutputStream(target)!!.use { out ->
                api.download(jobId, out) { done, total ->
                    val now = System.currentTimeMillis()
                    if (now - last > 700 && total > 0) {
                        last = now
                        setProgressAsyncSafe(STAGE_DOWNLOAD, done.toFloat() / total,
                            "Downloading ${percent(done, total)}", jobId = jobId)
                    }
                }
            }
            values.clear()
            values.put(MediaStore.Video.Media.IS_PENDING, 0)
            cr.update(target, values, null, null)
            return target
        } catch (e: Exception) {
            cr.delete(target, null, null)
            throw e
        }
    }

    // ---------------------------------------------------------------- progress
    private suspend fun report(
        stage: String, frac: Float, label: String, eta: Long? = null,
        jobId: String? = null, speakers: Int? = null,
    ) {
        setProgress(progressData(stage, frac, label, eta, jobId, speakers))
        // May be refused when started from the background on Android 12+; progress still works.
        runCatching { setForeground(foregroundInfo(label, frac)) }
            .onFailure { notify(label, frac, done = false) }
    }

    private fun setProgressAsyncSafe(stage: String, frac: Float, label: String, jobId: String? = null) {
        setProgressAsync(progressData(stage, frac, label, null, jobId, null))
        notify(label, frac, done = false)
    }

    private fun progressData(stage: String, frac: Float, label: String, eta: Long?, jobId: String?, speakers: Int?) =
        workDataOf(
            KEY_STAGE to stage, KEY_PROGRESS to frac.coerceIn(0f, 1f), KEY_LABEL to label,
            KEY_ETA to (eta ?: -1L), KEY_JOB to jobId, KEY_SPEAKERS to (speakers ?: -1),
        )

    override suspend fun getForegroundInfo(): ForegroundInfo = foregroundInfo("Preparing…", 0f)

    private fun foregroundInfo(text: String, frac: Float?): ForegroundInfo =
        ForegroundInfo(notifId, buildNotification(text, frac, ongoing = true),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)

    private fun buildNotification(text: String, frac: Float?, ongoing: Boolean): Notification {
        val open = PendingIntent.getActivity(
            applicationContext, 0, Intent(applicationContext, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(applicationContext, HindiDubApp.CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_dub)
            .setContentTitle("HindiDub")
            .setContentText(text)
            .setContentIntent(open)
            .setOnlyAlertOnce(true)
            .setOngoing(ongoing)
            .setAutoCancel(!ongoing)
            .apply { if (frac != null) setProgress(1000, (frac * 1000).toInt(), false) }
            .build()
    }

    @SuppressLint("MissingPermission")
    private fun notify(text: String, frac: Float?, done: Boolean) {
        val granted = ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) return
        runCatching {
            NotificationManagerCompat.from(applicationContext)
                .notify(if (done) notifId + 1 else notifId, buildNotification(text, frac, ongoing = !done))
        }
    }

    private fun notifyDone(name: String) = notify("Hindi video ready: $name", null, done = true)

    companion object {
        const val UNIQUE = "hindi-dub"
        const val KEY_URI = "uri"
        const val KEY_NAME = "name"
        const val KEY_SIZE = "size"
        const val KEY_STAGE = "stage"
        const val KEY_PROGRESS = "progress"
        const val KEY_LABEL = "label"
        const val KEY_ETA = "eta"
        const val KEY_JOB = "job"
        const val KEY_SPEAKERS = "speakers"
        const val KEY_RESULT = "result"
        const val KEY_ERROR = "error"

        const val STAGE_CONNECT = "connect"
        const val STAGE_UPLOAD = "upload"
        const val STAGE_SERVER = "server"
        const val STAGE_DOWNLOAD = "download"
        const val STAGE_RETRY = "retry"

        private const val CHUNK = 8 * 1024 * 1024
        private const val MAX_ATTEMPTS = 20

        fun enqueue(context: Context, uri: Uri, name: String, size: Long) {
            val req = OneTimeWorkRequestBuilder<DubWorker>()
                .setInputData(workDataOf(KEY_URI to uri.toString(), KEY_NAME to name, KEY_SIZE to size))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .addTag(UNIQUE)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(UNIQUE, ExistingWorkPolicy.REPLACE, req)
        }

        fun stageLabel(stage: String): String = when (stage) {
            "queued" -> "Waiting in queue"
            "extract" -> "Reading audio"
            "separate" -> "Separating voices from music"
            "transcribe" -> "Understanding English speech"
            "diarize" -> "Identifying characters"
            "references" -> "Learning each character's voice"
            "translate" -> "Translating to Hindi"
            "synthesize" -> "Speaking Hindi in each voice"
            "mix" -> "Mixing final audio"
            else -> "Processing"
        }

        private fun percent(a: Long, b: Long) = if (b <= 0) "" else "${(a * 100 / b)}%"
    }
}
