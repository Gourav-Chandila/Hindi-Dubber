package com.hindidub.app.media

import android.content.Context
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.net.Uri
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Takes only the English audio out of a video on the phone, so we upload
 * ~100-200 MB instead of the whole movie. AAC tracks are copied as-is (no
 * quality loss, seconds); other codecs (AC3, Opus, MP3, ...) are re-encoded
 * to AAC with the phone's own codecs. Returns null when the phone can't do it
 * (unusual codecs) - the caller then uploads the full video like before.
 */
object AudioPrep {
    private const val AAC = MediaFormat.MIMETYPE_AUDIO_AAC
    private val ENGLISH = setOf("eng", "en", "english")

    /** Video codecs Android's MP4 muxer can copy without re-encoding. */
    val MUXABLE_VIDEO = setOf(
        MediaFormat.MIMETYPE_VIDEO_AVC, MediaFormat.MIMETYPE_VIDEO_HEVC,
        MediaFormat.MIMETYPE_VIDEO_MPEG4, MediaFormat.MIMETYPE_VIDEO_H263,
    )

    data class Prepared(val file: File, val language: String?, val startUs: Long)

    fun language(f: MediaFormat): String? =
        if (f.containsKey(MediaFormat.KEY_LANGUAGE)) f.getString(MediaFormat.KEY_LANGUAGE)?.lowercase() else null

    fun prepare(ctx: Context, uri: Uri, out: File): Prepared? {
        val ex = MediaExtractor()
        return try {
            ex.setDataSource(ctx, uri, null)
            var videoMime: String? = null
            val audio = mutableListOf<Pair<Int, MediaFormat>>()
            for (i in 0 until ex.trackCount) {
                val f = ex.getTrackFormat(i)
                val mime = f.getString(MediaFormat.KEY_MIME) ?: continue
                if (mime.startsWith("video/") && videoMime == null) videoMime = mime
                if (mime.startsWith("audio/")) audio += i to f
            }
            // The phone must be able to put the Hindi track back into this video later.
            if (videoMime !in MUXABLE_VIDEO || audio.isEmpty()) return null
            val (track, fmt) = audio.firstOrNull { language(it.second) in ENGLISH } ?: audio.first()
            out.parentFile?.mkdirs()
            val startUs = if (fmt.getString(MediaFormat.KEY_MIME) == AAC) remux(ex, track, fmt, out)
            else transcode(ex, track, fmt, out)
            if (out.length() < 1024) null else Prepared(out, language(fmt), startUs)
        } catch (e: Exception) {
            out.delete()
            null
        } finally {
            ex.release()
        }
    }

    private fun bufferSize(fmt: MediaFormat): Int =
        max(if (fmt.containsKey(MediaFormat.KEY_MAX_INPUT_SIZE)) fmt.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE) else 0,
            256 * 1024)

    /** Copy an AAC track into an .m4a; timestamps start at 0, returns the original start. */
    private fun remux(ex: MediaExtractor, track: Int, fmt: MediaFormat, out: File): Long {
        ex.selectTrack(track)
        val muxer = MediaMuxer(out.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        try {
            val dst = muxer.addTrack(fmt)
            muxer.start()
            val buf = ByteBuffer.allocate(bufferSize(fmt))
            val info = MediaCodec.BufferInfo()
            var first = -1L
            while (true) {
                val n = ex.readSampleData(buf, 0)
                if (n < 0) break
                val t = ex.sampleTime
                if (first < 0) first = t
                info.set(0, n, t - first, 0)
                muxer.writeSampleData(dst, buf, info)
                ex.advance()
            }
            muxer.stop()
            return max(first, 0L)
        } finally {
            muxer.release()
        }
    }

    /** Decode any audio codec the phone supports -> stereo PCM -> AAC 160 kb/s .m4a. */
    private fun transcode(ex: MediaExtractor, track: Int, fmt: MediaFormat, out: File): Long {
        ex.selectTrack(track)
        val first = max(ex.sampleTime, 0L)
        val dec = MediaCodec.createDecoderByType(fmt.getString(MediaFormat.KEY_MIME)!!)
        dec.configure(fmt, null, null, 0)
        dec.start()
        var enc: MediaCodec? = null
        val muxer = MediaMuxer(out.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        var muxTrack = -1
        val info = MediaCodec.BufferInfo()
        val inBuf = ByteBuffer.allocate(bufferSize(fmt))
        val pcm = ShortQueue()
        var inEos = false
        var decEos = false
        var encInEos = false
        var encEos = false
        var sampleRate = 0
        var inCh = 0
        var isFloat = false
        var framesFed = 0L
        try {
            while (!encEos) {
                // 1) compressed samples -> decoder
                if (!inEos) {
                    val i = dec.dequeueInputBuffer(5_000)
                    if (i >= 0) {
                        val n = ex.readSampleData(inBuf, 0)
                        val b = dec.getInputBuffer(i)!!
                        if (n < 0) {
                            dec.queueInputBuffer(i, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inEos = true
                        } else {
                            b.clear(); inBuf.limit(n); inBuf.position(0); b.put(inBuf); inBuf.clear()
                            dec.queueInputBuffer(i, 0, n, max(ex.sampleTime - first, 0L), 0)
                            ex.advance()
                        }
                    }
                }
                // 2) decoder -> stereo 16-bit PCM queue
                if (!decEos) {
                    val o = dec.dequeueOutputBuffer(info, 5_000)
                    if (o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                        val f = dec.outputFormat
                        sampleRate = f.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                        inCh = f.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                        isFloat = f.containsKey(MediaFormat.KEY_PCM_ENCODING) &&
                            f.getInteger(MediaFormat.KEY_PCM_ENCODING) == android.media.AudioFormat.ENCODING_PCM_FLOAT
                        enc = startEncoder(sampleRate)
                    } else if (o >= 0) {
                        if (info.size > 0 && inCh > 0) {
                            val b = dec.getOutputBuffer(o)!!.order(ByteOrder.nativeOrder())
                            b.position(info.offset); b.limit(info.offset + info.size)
                            pcm.add(toStereo(b, inCh, isFloat))
                        }
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) decEos = true
                        dec.releaseOutputBuffer(o, false)
                    }
                }
                val e = enc ?: if (decEos) throw IllegalStateException("no audio decoded") else continue
                // 3) PCM -> encoder
                if (!encInEos && (pcm.size >= 2048 || decEos)) {
                    val i = e.dequeueInputBuffer(5_000)
                    if (i >= 0) {
                        val b = e.getInputBuffer(i)!!.order(ByteOrder.nativeOrder())
                        b.clear()
                        val shorts = minOf(pcm.size, b.capacity() / 2) and 1.inv() // whole stereo frames
                        pcm.drainTo(b, shorts)
                        val pts = framesFed * 1_000_000L / sampleRate
                        framesFed += shorts / 2
                        val eos = decEos && pcm.size == 0
                        e.queueInputBuffer(i, 0, shorts * 2, pts, if (eos) MediaCodec.BUFFER_FLAG_END_OF_STREAM else 0)
                        if (eos) encInEos = true
                    }
                }
                // 4) encoder -> muxer
                val o = e.dequeueOutputBuffer(info, 5_000)
                if (o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    muxTrack = muxer.addTrack(e.outputFormat)
                    muxer.start()
                } else if (o >= 0) {
                    val isConfig = info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                    if (!isConfig && info.size > 0 && muxTrack >= 0) {
                        muxer.writeSampleData(muxTrack, e.getOutputBuffer(o)!!, info)
                    }
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) encEos = true
                    e.releaseOutputBuffer(o, false)
                }
            }
            muxer.stop()
            return first
        } finally {
            runCatching { dec.stop() }; dec.release()
            enc?.let { runCatching { it.stop() }; it.release() }
            runCatching { muxer.release() }
        }
    }

    private fun startEncoder(sampleRate: Int): MediaCodec {
        val f = MediaFormat.createAudioFormat(AAC, sampleRate, 2).apply {
            setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
            setInteger(MediaFormat.KEY_BIT_RATE, 160_000)
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 64 * 1024)
        }
        return MediaCodec.createEncoderByType(AAC).apply {
            configure(f, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            start()
        }
    }

    /** Interleaved PCM with any channel count -> interleaved stereo shorts. */
    private fun toStereo(b: ByteBuffer, ch: Int, isFloat: Boolean): ShortArray {
        val samples = if (isFloat) b.remaining() / 4 else b.remaining() / 2
        val frames = samples / ch
        val src = FloatArray(samples)
        if (isFloat) b.asFloatBuffer().get(src) else {
            val s = ShortArray(samples); b.asShortBuffer().get(s)
            for (k in s.indices) src[k] = s[k] / 32768f
        }
        val out = ShortArray(frames * 2)
        for (fr in 0 until frames) {
            val x = fr * ch
            val (l, r) = when {
                ch == 1 -> src[x] to src[x]
                ch == 2 -> src[x] to src[x + 1]
                // 5.1 / 7.1 (FL FR FC LFE BL BR ...): standard downmix
                ch >= 6 -> (0.6f * (src[x] + 0.707f * src[x + 2] + 0.707f * src[x + 4])) to
                    (0.6f * (src[x + 1] + 0.707f * src[x + 2] + 0.707f * src[x + 5]))
                else -> (0.7f * (src[x] + 0.5f * src[x + 2])) to (0.7f * (src[x + 1] + 0.5f * src[x + 2]))
            }
            out[fr * 2] = (l.coerceIn(-1f, 1f) * 32767f).roundToInt().toShort()
            out[fr * 2 + 1] = (r.coerceIn(-1f, 1f) * 32767f).roundToInt().toShort()
        }
        return out
    }

    /** FIFO of PCM shorts fed to the encoder in buffer-sized pieces. */
    private class ShortQueue {
        private val chunks = ArrayDeque<ShortArray>()
        private var headPos = 0
        var size = 0
            private set

        fun add(a: ShortArray) {
            if (a.isNotEmpty()) { chunks.addLast(a); size += a.size }
        }

        fun drainTo(b: ByteBuffer, count: Int) {
            var left = count
            while (left > 0) {
                val head = chunks.first()
                val take = minOf(left, head.size - headPos)
                for (k in 0 until take) b.putShort(head[headPos + k])
                headPos += take; left -= take; size -= take
                if (headPos == head.size) { chunks.removeFirst(); headPos = 0 }
            }
        }
    }
}
