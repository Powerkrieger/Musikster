package com.example.musikster

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import com.spotify.android.appremote.api.ConnectionParams
import com.spotify.android.appremote.api.Connector
import com.spotify.android.appremote.api.SpotifyAppRemote
import com.spotify.protocol.types.Image
import com.spotify.protocol.types.ImageUri
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/** A track as reported by App Remote's PlayerState. */
data class TrackInfo(
    val uri: String,
    val spotifyTrackId: String,
    val name: String,
    val artist: String,
    val durationMs: Long,
    val imageUriRaw: String = "",
    val year: Int? = null
)

/**
 * Controls Spotify playback via the App Remote SDK (IPC with the Spotify app —
 * requires Spotify Premium and the app installed on-device). Adapted from
 * QuickMusicQuiz's SpotifyPlaybackManager; adds trackIdFromUri() since the deck
 * builder needs bare track IDs, not just full spotify: URIs.
 */
class SpotifyPlaybackManager(
    private val context: Context
) {

    private var appRemote: SpotifyAppRemote? = null

    val isConnected: Boolean get() = appRemote?.isConnected == true

    fun connect(onConnected: () -> Unit, onFailure: (String) -> Unit) {
        val params = ConnectionParams.Builder(SpotifyAuthManager.CLIENT_ID)
            .setRedirectUri(SpotifyAuthManager.REDIRECT_URI)
            .showAuthView(true)
            .build()

        SpotifyAppRemote.connect(context, params, object : Connector.ConnectionListener {
            override fun onConnected(remote: SpotifyAppRemote) {
                appRemote = remote
                onConnected()
            }

            override fun onFailure(throwable: Throwable) {
                appRemote = null
                // The SDK often surfaces a null-message throwable ("Unknown Spotify error"
                // downstream) — the exception's class name is what actually pins down the cause.
                Log.e("SpotifyPlaybackManager", "App Remote connect() failed", throwable)
                onFailure(throwable.localizedMessage ?: "Unknown Spotify error (${throwable.javaClass.simpleName})")
            }
        })
    }

    fun disconnect() {
        appRemote?.let { SpotifyAppRemote.disconnect(it) }
        appRemote = null
    }

    suspend fun getCurrentTrack(): TrackInfo? = suspendCancellableCoroutine { cont ->
        val remote = appRemote
        if (remote == null) {
            cont.resume(null)
            return@suspendCancellableCoroutine
        }

        remote.playerApi.playerState
            .setResultCallback { state ->
                if (cont.isCompleted) return@setResultCallback
                val track = state.track
                if (track == null) {
                    cont.resume(null)
                } else {
                    cont.resume(
                        TrackInfo(
                            uri = track.uri ?: "",
                            spotifyTrackId = trackIdFromUri(track.uri ?: ""),
                            name = track.name ?: "Unknown",
                            artist = track.artist?.name ?: "Unknown",
                            durationMs = track.duration,
                            imageUriRaw = track.imageUri?.raw ?: ""
                        )
                    )
                }
            }
            .setErrorCallback {
                if (!cont.isCompleted) cont.resume(null)
            }
    }

    suspend fun getTrackImage(imageUriRaw: String): Bitmap? = suspendCancellableCoroutine { cont ->
        val remote = appRemote
        if (remote == null || imageUriRaw.isEmpty()) {
            cont.resume(null)
            return@suspendCancellableCoroutine
        }
        remote.imagesApi
            .getImage(ImageUri(imageUriRaw), Image.Dimension.LARGE)
            .setResultCallback { bitmap ->
                if (!cont.isCompleted) cont.resume(bitmap)
            }
            .setErrorCallback {
                if (!cont.isCompleted) cont.resume(null)
            }
    }

    suspend fun playTrackAt(trackUri: String, startPositionMs: Long) {
        val remote = appRemote ?: return
        remote.playerApi.play(trackUri)
        if (startPositionMs > 0L) {
            delay(700)
            remote.playerApi.seekTo(startPositionMs)
        }
    }

    fun seekTo(positionMs: Long) { appRemote?.playerApi?.seekTo(positionMs) }
    fun pause() { appRemote?.playerApi?.pause() }
    fun resume() { appRemote?.playerApi?.resume() }

    companion object {
        /** "spotify:track:4iV5W9uYEdYUVa79Axb7Rh" -> "4iV5W9uYEdYUVa79Axb7Rh" */
        fun trackIdFromUri(uri: String): String = uri.substringAfterLast(':')
    }
}
