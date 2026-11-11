package com.hindidub.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.core.content.IntentCompat
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import com.hindidub.app.ui.HindiDubTheme
import com.hindidub.app.ui.MainScreen
import com.hindidub.app.ui.MainViewModel

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) sharedVideo(intent)?.let { vm.onVideoPicked(it, persist = false) }
        setContent { HindiDubTheme { MainScreen(vm) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        sharedVideo(intent)?.let { vm.onVideoPicked(it, persist = false) }
    }

    private fun sharedVideo(intent: Intent?): Uri? =
        if (intent?.action == Intent.ACTION_SEND)
            IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
        else null
}
