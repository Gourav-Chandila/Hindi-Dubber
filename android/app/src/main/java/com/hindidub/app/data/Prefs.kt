package com.hindidub.app.data

import android.content.Context
import androidx.core.content.edit
import com.hindidub.app.BuildConfig

/** Small key/value store for settings and for resuming a dub after a restart. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("hindidub", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server_url", null)?.takeIf { it.isNotBlank() } ?: BuildConfig.DEFAULT_SERVER_URL
        set(v) = sp.edit { putString("server_url", v.trim().trimEnd('/')) }

    var apiKey: String
        get() = sp.getString("api_key", null)?.takeIf { it.isNotBlank() } ?: BuildConfig.DEFAULT_API_KEY
        set(v) = sp.edit { putString("api_key", v.trim()) }

    /** Exact number of characters (0 = detect automatically). */
    var speakers: Int
        get() = sp.getInt("speakers", 0)
        set(v) = sp.edit { putInt("speakers", v.coerceIn(0, 10)) }

    /** "studio" = clear distinct voices, "clone" = imitate each actor. */
    var voiceMode: String
        get() = sp.getString("voice_mode", "studio") ?: "studio"
        set(v) = sp.edit { putString("voice_mode", v) }

    var lastResultUri: String?
        get() = sp.getString("last_result", null)
        set(v) = sp.edit { putString("last_result", v) }

    var lastResultName: String?
        get() = sp.getString("last_result_name", null)
        set(v) = sp.edit { putString("last_result_name", v) }

    // Per-work resume state (keyed by WorkManager work id).
    fun uploadId(work: String): String? = sp.getString("upload_$work", null)
    fun setUploadId(work: String, id: String?) = sp.edit { putString("upload_$work", id) }
    fun jobId(work: String): String? = sp.getString("job_$work", null)
    fun setJobId(work: String, id: String?) = sp.edit { putString("job_$work", id) }
    /** "audio" = only the audio is sent (small), "video" = whole video (fallback). */
    fun prepMode(work: String): String? = sp.getString("prep_mode_$work", null)
    fun prepStartUs(work: String): Long = sp.getLong("prep_start_$work", 0L)
    fun prepLang(work: String): String? = sp.getString("prep_lang_$work", null)
    fun setPrep(work: String, mode: String, startUs: Long, lang: String?) = sp.edit {
        putString("prep_mode_$work", mode); putLong("prep_start_$work", startUs); putString("prep_lang_$work", lang)
    }
    fun clearWork(work: String) = sp.edit {
        remove("upload_$work"); remove("job_$work")
        remove("prep_mode_$work"); remove("prep_start_$work"); remove("prep_lang_$work")
    }
}
