package com.hindidub.app.media

import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.net.Uri
import java.io.File
import java.io.FileDescriptor
import java.nio.ByteBuffer
import kotlin.math.max

/**
 * Builds the final video on the phone: the original video stream copied
 * bit-for-bit (never re-encoded) + Hindi audio (first/default track) + the
 * English audio that was uploaded. Takes seconds, even for a full movie.
 */
object HindiMuxer {

    private class Source(val ex: MediaExtractor, val track: Int, val offsetUs: Long) {
        var done = false
        val nextTime: Long get() = ex.sampleTime + offsetUs
    }

    fun mux(ctx: Context, video: Uri, hindi: File, english: File?, englishLang: String?,
            audioStartUs: Long, out: FileDescriptor, onProgress: (Float) -> Unit = {}) {
        val muxer = MediaMuxer(out, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        val extractors = mutableListOf<MediaExtractor>()
        try {
            val sources = mutableListOf<Source>()
            var maxInput = 1024 * 1024
            var durationUs = 1L

            // 1) original video stream, copied as-is
            val vex = MediaExtractor().also { extractors += it }
            vex.setDataSource(ctx, video, null)
            val vt = (0 until vex.trackCount).first {
                vex.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true
            }
            val vfmt = vex.getTrackFormat(vt)
            if (vfmt.containsKey(MediaFormat.KEY_ROTATION)) muxer.setOrientationHint(vfmt.getInteger(MediaFormat.KEY_ROTATION))
            if (vfmt.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)) maxInput = max(maxInput, vfmt.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE))
            if (vfmt.containsKey(MediaFormat.KEY_DURATION)) durationUs = max(durationUs, vfmt.getLong(MediaFormat.KEY_DURATION))
            vex.selectTrack(vt)
            sources += Source(vex, muxer.addTrack(vfmt), 0L)

            // 2) Hindi (default) and 3) English audio, both placed where the original audio started
            fun addAudio(file: File, lang: String) {
                val ex = MediaExtractor().also { extractors += it }
                ex.setDataSource(file.path)
                val f = ex.getTrackFormat(0)
                f.setString(MediaFormat.KEY_LANGUAGE, lang)
                if (f.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)) maxInput = max(maxInput, f.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE))
                ex.selectTrack(0)
                sources += Source(ex, muxer.addTrack(f), audioStartUs)
            }
            addAudio(hindi, "hin")
            if (english != null && english.exists()) addAudio(english, englishLang?.takeIf { it.length == 3 } ?: "eng")

            muxer.start()
            val buf = ByteBuffer.allocate(maxInput)
            val info = MediaCodec.BufferInfo()
            var lastReport = 0L
            // Write samples in time order across tracks so the file plays smoothly.
            while (true) {
                val s = sources.filter { !it.done }.minByOrNull { it.nextTime } ?: break
                val n = s.ex.readSampleData(buf, 0)
                if (n < 0) { s.done = true; continue }
                val t = s.nextTime
                val key = s.ex.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC != 0
                info.set(0, n, max(t, 0L), if (key) MediaCodec.BUFFER_FLAG_KEY_FRAME else 0)
                muxer.writeSampleData(s.track, buf, info)
                s.ex.advance()
                if (t - lastReport > 2_000_000) { lastReport = t; onProgress((t.toFloat() / durationUs).coerceIn(0f, 1f)) }
            }
            muxer.stop()
        } finally {
            runCatching { muxer.release() }
            extractors.forEach { it.release() }
        }
    }
}
