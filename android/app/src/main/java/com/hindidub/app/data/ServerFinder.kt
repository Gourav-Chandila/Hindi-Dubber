package com.hindidub.app.data

import android.net.Uri
import com.hindidub.app.BuildConfig
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Finds the current server address. The Kaggle server uses a free Cloudflare
 * tunnel whose address changes every run; it announces the address on a
 * private ntfy.sh topic derived from the HindiDub API key (same formula as
 * notebooks/tunnel.py), and the app reads the newest one from there.
 */
object ServerFinder {
    private val http = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    fun keyFor(prefs: Prefs): String =
        prefs.apiKey.ifEmpty { Uri.parse(BuildConfig.DEFAULT_SERVER_URL).host.orEmpty() }

    fun topic(key: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(key.toByteArray())
        return "hindidub-" + digest.joinToString("") { "%02x".format(it) }.take(24)
    }

    /** Newest announced https address, or null if none / not reachable. */
    fun latestUrl(key: String): String? {
        if (key.isEmpty()) return null
        return try {
            val req = Request.Builder().url("https://ntfy.sh/${topic(key)}/json?poll=1&since=12h").build()
            http.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) return null
                resp.body?.string().orEmpty().lineSequence()
                    .filter { it.isNotBlank() }
                    .mapNotNull { runCatching { JSONObject(it) }.getOrNull() }
                    .filter { it.optString("event") == "message" }
                    .map { it.optString("message").trim().trimEnd('/') }
                    .lastOrNull { it.startsWith("https://") }
            }
        } catch (e: Exception) {
            null
        }
    }
}
