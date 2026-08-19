package com.example.musikster

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.example.musikster.ui.theme.MusiksterTheme

class MainActivity : ComponentActivity() {

    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        handleRedirectIntent(intent)

        setContent {
            MusiksterTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    MusiksterApp(viewModel)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleRedirectIntent(intent)
    }

    override fun onStart() {
        super.onStart()
        if (viewModel.authManager.isAuthenticated()) {
            viewModel.playbackManager.connect(
                onConnected = { viewModel.onAppRemoteConnected() },
                onFailure = { error -> viewModel.onAppRemoteFailure(error) }
            )
        }
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
    val deckCardCount by viewModel.deckCardCount.collectAsState()
    val deckImportMessage by viewModel.deckImportMessage.collectAsState()

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

    Box(Modifier.fillMaxSize()) {
        when (appMode) {
            is AppMode.NotConnected -> NotConnectedScreen(onConnect = { viewModel.startAuth() })
            is AppMode.Authenticating -> AuthenticatingScreen()
            is AppMode.Home -> HomeScreen(
                isRemoteConnected = isRemoteConnected,
                errorMessage = errorMessage,
                deckCardCount = deckCardCount,
                deckImportMessage = deckImportMessage,
                onPlay = { viewModel.openScanPlay() },
                onImportDeck = {
                    viewModel.clearDeckImportMessage()
                    importDeckLauncher.launch("application/json")
                }
            )
            is AppMode.ScanPlay -> ScanPlayScreen(viewModel.scanPlay)
        }

        if (showHomeButton) {
            TextButton(
                onClick = { viewModel.goHome() },
                modifier = Modifier.align(Alignment.TopStart).padding(top = 40.dp, start = 8.dp)
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
