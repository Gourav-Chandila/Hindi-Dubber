@file:OptIn(ExperimentalMaterial3Api::class)

package com.hindidub.app.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.RecordVoiceOver
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView


@Composable
fun MainScreen(vm: MainViewModel) {
    val state by vm.state.collectAsState()
    val picked by vm.picked.collectAsState()
    var showSettings by rememberSaveable { mutableStateOf(false) }

    val pickVideo = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) vm.onVideoPicked(uri, persist = true)
    }
    val notifPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        vm.startDub() // start either way; notifications are optional
    }
    val start = {
        if (Build.VERSION.SDK_INT >= 33) notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        else vm.startDub()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("HindiDub", fontWeight = FontWeight.Bold) },
                actions = {
                    IconButton(onClick = { showSettings = !showSettings }) {
                        Icon(Icons.Filled.Settings, contentDescription = "Server settings")
                    }
                },
            )
        },
    ) { pad ->
        Column(
            Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            AnimatedVisibility(showSettings) { SettingsCard(vm) }

            Text(
                "English video → Hindi dub. Every character keeps their own consistent voice; " +
                    "the picture is never changed.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            when (val s = state) {
                is DubState.Running -> ProgressCard(s, onCancel = vm::cancel)
                is DubState.Done -> ResultCard(s, onNew = vm::reset)
                is DubState.Failed -> {
                    ErrorCard(s.message, onRetry = { if (picked != null) start() else vm.reset() })
                    PickCard(picked, onPick = { pickVideo.launch(arrayOf("video/*")) }, onStart = start)
                }
                DubState.Idle -> PickCard(picked, onPick = { pickVideo.launch(arrayOf("video/*")) }, onStart = start)
            }
        }
    }
}

@Composable
private fun SettingsCard(vm: MainViewModel) {
    val server by vm.server.collectAsState()
    val key by vm.apiKey.collectAsState()
    val check by vm.check.collectAsState()
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Server", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(server, vm::setServer, label = { Text("Server URL") },
                singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(key, vm::setApiKey, label = { Text("API key (optional)") },
                singleLine = true, visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(onClick = vm::testServer, enabled = !check.checking) { Text("Test connection") }
                Spacer(Modifier.width(12.dp))
                if (check.checking) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
            }
            check.message?.let {
                Text(it, color = if (check.ok == false) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun PickCard(picked: PickedVideo?, onPick: () -> Unit, onStart: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            FilledTonalButton(onClick = onPick, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Filled.VideoLibrary, null)
                Spacer(Modifier.width(8.dp))
                Text(if (picked == null) "Pick English video" else "Pick another video")
            }
            if (picked != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.Movie, null)
                    Spacer(Modifier.width(8.dp))
                    Column {
                        Text(picked.name, fontWeight = FontWeight.SemiBold)
                        if (picked.size > 0) Text(formatSize(picked.size), style = MaterialTheme.typography.bodySmall)
                    }
                }
                Button(onClick = onStart, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.RecordVoiceOver, null)
                    Spacer(Modifier.width(8.dp))
                    Text("Dub to Hindi")
                }
                Text(
                    "You can close the app – dubbing continues in the background and you'll get a notification.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ProgressCard(s: DubState.Running, onCancel: () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stepTitle(s.stage), style = MaterialTheme.typography.titleMedium)
            Text(s.label)
            if (s.progress > 0f) LinearProgressIndicator(progress = { s.progress }, modifier = Modifier.fillMaxWidth())
            else LinearProgressIndicator(Modifier.fillMaxWidth())
            Row {
                Text("${(s.progress * 100).toInt()}%", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.weight(1f))
                s.etaSeconds?.let { Text("About ${formatEta(it)} left", style = MaterialTheme.typography.bodySmall) }
            }
            s.speakers?.let { Text("$it character voice(s) detected", style = MaterialTheme.typography.bodySmall) }
            OutlinedButton(onClick = onCancel) {
                Icon(Icons.Filled.Close, null)
                Spacer(Modifier.width(8.dp))
                Text("Cancel")
            }
        }
    }
}

@Composable
private fun ResultCard(s: DubState.Done, onNew: () -> Unit) {
    val ctx = LocalContext.current
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Hindi video ready", style = MaterialTheme.typography.titleMedium)
            Text("Saved to Movies/HindiDub · ${s.name}", style = MaterialTheme.typography.bodySmall)
            VideoPlayer(s.uri)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = "video/mp4"
                        putExtra(Intent.EXTRA_STREAM, s.uri)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    ctx.startActivity(Intent.createChooser(send, "Share Hindi video"))
                }) {
                    Icon(Icons.Filled.Share, null)
                    Spacer(Modifier.width(8.dp))
                    Text("Share")
                }
                OutlinedButton(onClick = onNew) { Text("Dub another") }
            }
        }
    }
}

@Composable
private fun VideoPlayer(uri: Uri) {
    val ctx = LocalContext.current
    val player = remember(uri) {
        ExoPlayer.Builder(ctx).build().apply {
            trackSelectionParameters = trackSelectionParameters.buildUpon().setPreferredAudioLanguage("hi").build()
            setMediaItem(MediaItem.fromUri(uri))
            prepare()
        }
    }
    DisposableEffect(player) { onDispose { player.release() } }
    var lang by rememberSaveable { mutableStateOf("hi") }

    AndroidView(
        factory = { PlayerView(it).apply { this.player = player } },
        modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f),
    )
    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
        listOf("hi" to "Hindi", "en" to "English (original)").forEachIndexed { i, (code, label) ->
            SegmentedButton(
                selected = lang == code,
                onClick = {
                    lang = code
                    player.trackSelectionParameters =
                        player.trackSelectionParameters.buildUpon().setPreferredAudioLanguage(code).build()
                },
                shape = SegmentedButtonDefaults.itemShape(i, 2),
            ) { Text(label) }
        }
    }
}

@Composable
private fun ErrorCard(message: String, onRetry: () -> Unit) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.ErrorOutline, null)
                Spacer(Modifier.width(8.dp))
                Text("Dubbing failed", fontWeight = FontWeight.SemiBold)
            }
            Text(message)
            OutlinedButton(onClick = onRetry) {
                Icon(Icons.Filled.Refresh, null)
                Spacer(Modifier.width(8.dp))
                Text("Retry")
            }
        }
    }
}

private fun stepTitle(stage: String) = when (stage) {
    "connect" -> "Step 1 of 4 · Connecting"
    "upload" -> "Step 2 of 4 · Uploading"
    "server" -> "Step 3 of 4 · Dubbing"
    "download" -> "Step 4 of 4 · Downloading"
    "retry" -> "Reconnecting"
    else -> "Working"
}

private fun formatSize(b: Long): String = when {
    b >= 1L shl 30 -> "%.2f GB".format(b / (1L shl 30).toDouble())
    b >= 1L shl 20 -> "%.1f MB".format(b / (1L shl 20).toDouble())
    else -> "${b / 1024} KB"
}

private fun formatEta(s: Long): String = when {
    s >= 3600 -> "${s / 3600} h ${(s % 3600) / 60} min"
    s >= 60 -> "${s / 60} min"
    else -> "$s s"
}
