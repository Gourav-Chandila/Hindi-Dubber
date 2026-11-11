package com.hindidub.app.data

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.io.OutputStream
import java.util.concurrent.TimeUnit

class ApiException(val code: Int, message: String) : IOException(message)

data class JobStatus(
    val id: String,
    val status: String,      // uploading | queued | running | done | failed | cancelled
    val stage: String,
    val progress: Float,
    val etaSeconds: Long?,
    val queuePosition: Int,
    val error: String?,
    val speakers: Int?,
)

/** Thin client for the HindiDub backend. All calls are blocking: run them off the main thread. */
class Api(baseUrl: String, private val apiKey: String) {
    private val base = baseUrl.trimEnd('/')

    // Free Hugging Face Spaces can take ~1 min to wake up, so be patient.
    private val http = OkHttpClient.Builder()
        .connectTimeout(60, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)
        .writeTimeout(180, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()

    private val json = "application/json".toMediaType()
    private val octet = "application/octet-stream".toMediaType()

    private fun req(path: String) = Request.Builder().url("$base$path").apply {
        if (apiKey.isNotEmpty()) header("X-API-Key", apiKey)
    }

    private fun call(r: Request): JSONObject = http.newCall(r).execute().use { resp ->
        val body = resp.body?.string().orEmpty()
        if (!resp.isSuccessful) throw ApiException(resp.code, errorText(resp, body))
        if (body.isBlank()) JSONObject() else JSONObject(body)
    }

    private fun errorText(resp: Response, body: String): String {
        val detail = runCatching { JSONObject(body).opt("detail")?.toString() }.getOrNull()
        return when (resp.code) {
            401 -> "Server rejected the API key."
            404 -> detail ?: "Not found on server."
            413 -> detail ?: "Video is too large for this server."
            502, 503, 504 -> "Server is starting up or busy. Retrying…"
            else -> detail ?: "Server error ${resp.code}"
        }
    }

    fun health(): JSONObject = call(req("/health").get().build())

    fun createUpload(name: String, size: Long): String {
        val payload = JSONObject().put("filename", name).put("size", size).toString()
        return call(req("/uploads").post(payload.toRequestBody(json)).build()).getString("upload_id")
    }

    fun uploadReceived(uploadId: String): Long =
        call(req("/uploads/$uploadId").get().build()).getLong("received")

    /** Returns the server's new byte count. On 409 returns the server's current count. */
    fun putChunk(uploadId: String, offset: Long, bytes: ByteArray, len: Int): Long = try {
        call(
            req("/uploads/$uploadId?offset=$offset")
                .put(bytes.toRequestBody(octet, 0, len)).build()
        ).getLong("received")
    } catch (e: ApiException) {
        if (e.code == 409) uploadReceived(uploadId) else throw e
    }

    fun completeUpload(uploadId: String): String =
        call(req("/uploads/$uploadId/complete").post(ByteArray(0).toRequestBody(json)).build())
            .getString("job_id")

    fun job(jobId: String): JobStatus {
        val o = call(req("/jobs/$jobId").get().build())
        val stats = o.optJSONObject("stats")
        return JobStatus(
            id = o.getString("id"),
            status = o.getString("status"),
            stage = o.optString("stage", ""),
            progress = o.optDouble("progress", 0.0).toFloat(),
            etaSeconds = if (o.isNull("eta_seconds")) null else o.optLong("eta_seconds"),
            queuePosition = o.optInt("queue_position", 0),
            error = if (o.isNull("error")) null else o.optString("error"),
            speakers = stats?.takeIf { it.has("speakers") }?.optInt("speakers"),
        )
    }

    fun cancel(jobId: String) {
        runCatching { http.newCall(req("/jobs/$jobId").delete().build()).execute().close() }
    }

    /** Streams the dubbed video into [out], reporting (downloaded, total). */
    fun download(jobId: String, out: OutputStream, onProgress: (Long, Long) -> Unit) {
        http.newCall(req("/jobs/$jobId/result").get().build()).execute().use { resp ->
            if (!resp.isSuccessful) throw ApiException(resp.code, "Download failed (${resp.code})")
            val body = resp.body ?: throw IOException("Empty response")
            val total = body.contentLength()
            val buf = ByteArray(256 * 1024)
            var done = 0L
            body.byteStream().use { input ->
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    done += n
                    onProgress(done, total)
                }
            }
        }
    }
}
