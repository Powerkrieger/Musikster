package com.example.musikster

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.SecureRandom
import javax.net.ssl.HttpsURLConnection

/**
 * PKCE OAuth against the Spotify Web API. Adapted from QuickMusicQuiz's
 * SpotifyAuthManager — same flow, new client id / redirect uri / prefs namespace.
 */
class SpotifyAuthManager(private val context: Context) {

    companion object {
        // Client ID comes from local.properties (SPOTIFY_CLIENT_ID=...), not checked into git.
        // See README.md for how to create the Spotify app and get this value.
        val CLIENT_ID = BuildConfig.SPOTIFY_CLIENT_ID
        const val REDIRECT_URI = "musikster://callback"

        const val SCOPES = "app-remote-control playlist-read-private playlist-read-collaborative"

        private const val PREFS_NAME = "spotify_auth_prefs"
        private const val KEY_ACCESS = "access_token"
        private const val KEY_REFRESH = "refresh_token"
        private const val KEY_EXPIRES = "expires_at_ms"
        private const val KEY_VERIFIER = "pkce_code_verifier"

        private const val TOKEN_URL = "https://accounts.spotify.com/api/token"
        private const val EXPIRY_BUFFER_MS = 60_000L
    }

    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private fun generateCodeVerifier(): String {
        val bytes = ByteArray(64)
        SecureRandom().nextBytes(bytes)
        return Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
    }

    private fun generateCodeChallenge(verifier: String): String {
        val hash = MessageDigest.getInstance("SHA-256")
            .digest(verifier.toByteArray(Charsets.US_ASCII))
        return Base64.encodeToString(hash, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
    }

    fun buildAuthorizationUrl(): String {
        val verifier = generateCodeVerifier()
        prefs.edit().putString(KEY_VERIFIER, verifier).apply()

        return Uri.parse("https://accounts.spotify.com/authorize").buildUpon()
            .appendQueryParameter("client_id", CLIENT_ID)
            .appendQueryParameter("response_type", "code")
            .appendQueryParameter("redirect_uri", REDIRECT_URI)
            .appendQueryParameter("code_challenge_method", "S256")
            .appendQueryParameter("code_challenge", generateCodeChallenge(verifier))
            .appendQueryParameter("scope", SCOPES)
            .build()
            .toString()
    }

    suspend fun exchangeCodeForToken(code: String): Boolean = withContext(Dispatchers.IO) {
        val verifier = prefs.getString(KEY_VERIFIER, null) ?: return@withContext false
        try {
            val body = buildString {
                append("client_id=").append(URLEncoder.encode(CLIENT_ID, "UTF-8"))
                append("&grant_type=authorization_code")
                append("&code=").append(URLEncoder.encode(code, "UTF-8"))
                append("&redirect_uri=").append(URLEncoder.encode(REDIRECT_URI, "UTF-8"))
                append("&code_verifier=").append(URLEncoder.encode(verifier, "UTF-8"))
            }
            val json = post(TOKEN_URL, body) ?: return@withContext false
            saveTokens(json)
            true
        } catch (e: Exception) {
            false
        }
    }

    suspend fun refreshTokenIfNeeded(): Boolean {
        if (!isTokenExpired()) return true
        val refreshToken = prefs.getString(KEY_REFRESH, null) ?: return false

        return withContext(Dispatchers.IO) {
            try {
                val body = buildString {
                    append("client_id=").append(URLEncoder.encode(CLIENT_ID, "UTF-8"))
                    append("&grant_type=refresh_token")
                    append("&refresh_token=").append(URLEncoder.encode(refreshToken, "UTF-8"))
                }
                val json = post(TOKEN_URL, body) ?: return@withContext false
                saveTokens(json)
                true
            } catch (e: Exception) {
                false
            }
        }
    }

    private fun post(url: String, body: String): JSONObject? {
        val connection = URL(url).openConnection() as HttpsURLConnection
        connection.requestMethod = "POST"
        connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
        connection.doOutput = true
        connection.connectTimeout = 10_000
        connection.readTimeout = 10_000

        connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        if (connection.responseCode != 200) return null
        return JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
    }

    private fun saveTokens(json: JSONObject) {
        val accessToken = json.getString("access_token")
        val expiresIn = json.getInt("expires_in")
        val refreshToken = json.optString("refresh_token", prefs.getString(KEY_REFRESH, "") ?: "")

        prefs.edit()
            .putString(KEY_ACCESS, accessToken)
            .putString(KEY_REFRESH, refreshToken)
            .putLong(KEY_EXPIRES, System.currentTimeMillis() + expiresIn * 1000L - EXPIRY_BUFFER_MS)
            .apply()
    }

    private fun isTokenExpired(): Boolean =
        System.currentTimeMillis() >= prefs.getLong(KEY_EXPIRES, 0L)

    fun getAccessToken(): String? = prefs.getString(KEY_ACCESS, null)

    fun isAuthenticated(): Boolean = !isTokenExpired() && getAccessToken() != null

    fun clearTokens() = prefs.edit().clear().apply()
}
