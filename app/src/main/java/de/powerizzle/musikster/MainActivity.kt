package de.powerizzle.musikster

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import de.powerizzle.musikster.ui.theme.MusiksterTheme

class MainActivity : ComponentActivity() {

    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // The phone lies face-up on the table while a song plays, and Spotify's own media
        // notification spells out the track name — the very thing players are supposed to guess.
        // An app can't suppress another app's notification, so instead we keep it out of sight:
        // no status bar to show it in (a swipe from the edge still reveals the bars), and the
        // screen stays awake so the phone never locks into a lock screen showing the same
        // media card. (Turning Spotify's notifications off in Android's settings does *not*
        // work — One UI keeps showing the media card, which the MediaSession drives rather than
        // the notification permission. See README's "Hiding the song title".)
        hideSystemBars()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        handleRedirectIntent(intent)

        setContent {
            MusiksterTheme {
                MusiksterApp(viewModel)
            }
        }
    }

    /** Returning from Spotify (login, or the app itself) brings the system bars back. */
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    private fun hideSystemBars() {
        WindowCompat.getInsetsController(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(WindowInsetsCompat.Type.systemBars())
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleRedirectIntent(intent)
    }

    override fun onStart() {
        super.onStart()
        viewModel.reconnectAppRemote(
            onConnected = { viewModel.onAppRemoteConnected() },
            onFailure = { error -> viewModel.onAppRemoteFailure(error) }
        )
    }

    override fun onStop() {
        super.onStop()
        viewModel.playbackManager.disconnect()
        viewModel.onAppRemoteDisconnected()
    }

    private fun handleRedirectIntent(intent: Intent?) {
        val uri = intent?.data ?: return
        if (uri.scheme == "musikster" && uri.host == "callback") {
            val code = uri.getQueryParameter("code") ?: return
            viewModel.handleAuthRedirect(code)
            viewModel.playbackManager.connect(
                onConnected = { viewModel.onAppRemoteConnected() },
                onFailure = { error -> viewModel.onAppRemoteFailure(error) }
            )
        }
    }
}

@Composable
fun MusiksterApp(viewModel: MainViewModel) {
    val appMode by viewModel.appMode.collectAsState()
    val authUrl by viewModel.authUrl.collectAsState()
    val isRemoteConnected by viewModel.isAppRemoteConnected.collectAsState()
    val errorMessage by viewModel.errorMessage.collectAsState()
    val decks by viewModel.decks.collectAsState()
    val conflictingCardIds by viewModel.conflictingCardIds.collectAsState()
    val deckImportMessage by viewModel.deckImportMessage.collectAsState()
    val backgroundGradient by viewModel.backgroundGradient.collectAsState()

    val context = LocalContext.current

    LaunchedEffect(authUrl) {
        val url = authUrl ?: return@LaunchedEffect
        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        viewModel.onAuthUrlConsumed()
    }

    val importDeckLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> uri?.let { viewModel.importDeck(it) } }

    val showHomeButton = appMode is AppMode.ScanPlay

    // A fresh two-color gradient each round (see MainViewModel.backgroundGradient), mirroring
    // QuickMusicQuiz's changing background. Drawn full-screen behind everything; the camera
    // preview during scanning covers it entirely, so it's only visible on the non-camera screens.
    val gradientBrush = Brush.linearGradient(
        listOf(Color(backgroundGradient.first), Color(backgroundGradient.second))
    )

    Box(Modifier.fillMaxSize().background(gradientBrush)) {
        Surface(color = Color.Transparent, contentColor = Color.White) {
            when (appMode) {
                is AppMode.NotConnected -> NotConnectedScreen(onConnect = { viewModel.startAuth() })
                is AppMode.Authenticating -> AuthenticatingScreen()
                is AppMode.Home -> HomeScreen(
                    isRemoteConnected = isRemoteConnected,
                    errorMessage = errorMessage,
                    decks = decks,
                    conflictingCardIds = conflictingCardIds,
                    deckImportMessage = deckImportMessage,
                    onPlay = { viewModel.openScanPlay() },
                    onSetDeckEnabled = { id, enabled -> viewModel.setDeckEnabled(id, enabled) },
                    onRemoveDeck = { id -> viewModel.removeDeck(id) },
                    onImportDeck = {
                        viewModel.clearDeckImportMessage()
                        // "*/*" rather than "application/json": file pickers/providers are
                        // inconsistent about the MIME type they report for .gz, so a narrower
                        // filter can hide a valid deck.json.gz. DeckRepository validates content.
                        importDeckLauncher.launch("*/*")
                    },
                    onLogoutSpotify = { viewModel.logoutSpotify() }
                )
                is AppMode.ScanPlay -> ScanPlayScreen(viewModel.scanPlay)
            }
        }

        if (showHomeButton) {
            TextButton(
                onClick = { viewModel.goHome() },
                modifier = Modifier.align(Alignment.TopStart).padding(top = 40.dp, start = 8.dp),
                colors = ButtonDefaults.textButtonColors(contentColor = Color.White)
            ) {
                Text("← Home")
            }
        }
    }
}

@Composable
fun NotConnectedScreen(onConnect: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(stringResource(R.string.app_name), style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(12.dp))
        Text(
            "Connect your Spotify Premium account to play.",
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center
        )
        Spacer(Modifier.height(32.dp))
        Button(onClick = onConnect) { Text("Connect with Spotify") }
    }
}

@Composable
fun AuthenticatingScreen() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator()
            Spacer(Modifier.height(16.dp))
            Text("Opening Spotify login…")
        }
    }
}
