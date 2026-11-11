package com.hindidub.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

class HindiDubApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW)
        )
    }

    companion object {
        const val CHANNEL_ID = "dubbing"
    }
}
