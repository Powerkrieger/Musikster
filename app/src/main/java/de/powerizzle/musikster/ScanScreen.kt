package de.powerizzle.musikster

import android.Manifest
import android.content.pm.PackageManager
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.NotFoundException
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import java.util.concurrent.Executors

/** Switches between the camera scanner and the (camera-free) playback controls. */
@Composable
fun ScanPlayScreen(viewModel: ScanPlayViewModel) {
    val state by viewModel.state.collectAsState()

    when (state) {
        is ScanPlayState.Scanning -> CameraScanScreen(
            hasDeck = viewModel.hasDeck(),
            onScanned = { viewModel.onCardScanned(it) }
        )
        else -> PlaybackScreen(
            state = state,
            onTogglePlayback = { viewModel.togglePlayback() },
            onScanNext = { viewModel.scanNext() },
            onRetry = { viewModel.retryScanning() }
        )
    }
}

@Composable
private fun CameraScanScreen(hasDeck: Boolean, onScanned: (String) -> Unit) {
    val context = LocalContext.current

    var hasCameraPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> hasCameraPermission = granted }

    LaunchedEffect(Unit) {
        if (!hasCameraPermission) permissionLauncher.launch(Manifest.permission.CAMERA)
    }

    if (!hasDeck) {
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text("No deck in play", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(8.dp))
            Text("Go back Home and switch a deck on, or use \"Import Deck\" to load a deck file (…-deck.json.gz).", textAlign = TextAlign.Center)
        }
        return
    }

    if (!hasCameraPermission) {
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text("Camera access is needed to scan cards.", textAlign = TextAlign.Center)
            Spacer(Modifier.height(16.dp))
            Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }) {
                Text("Grant Camera Permission")
            }
        }
        return
    }

    Box(Modifier.fillMaxSize()) {
        CameraPreviewWithScanner(onScanned = onScanned)
        Text(
            "Point the camera at a card's QR code",
            modifier = Modifier.align(Alignment.BottomCenter).padding(32.dp),
            color = androidx.compose.ui.graphics.Color.White,
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center
        )
    }
}

@Composable
private fun CameraPreviewWithScanner(onScanned: (String) -> Unit) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val onScannedState = rememberUpdatedState(onScanned)
    val cameraExecutor = remember { Executors.newSingleThreadExecutor() }
    val cameraProviderFuture = remember { ProcessCameraProvider.getInstance(context) }

    // Camera use cases are bound to the Activity lifecycle, which outlives this composable
    // (the playback screen replaces it while the Activity keeps running) — so unbind and stop
    // the analysis thread ourselves when the scanner goes away.
    DisposableEffect(Unit) {
        onDispose {
            if (cameraProviderFuture.isDone) {
                runCatching { cameraProviderFuture.get().unbindAll() }
            }
            cameraExecutor.shutdown()
        }
    }

    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = { ctx ->
            val previewView = PreviewView(ctx)
            val mainExecutor = ContextCompat.getMainExecutor(ctx)

            cameraProviderFuture.addListener({
                val cameraProvider = cameraProviderFuture.get()

                val preview = Preview.Builder().build().also {
                    it.surfaceProvider = previewView.surfaceProvider
                }

                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                val analyzer = QrCodeAnalyzer { text ->
                    // ViewModel state is touched on the main thread only.
                    mainExecutor.execute { onScannedState.value(text) }
                }
                analysis.setAnalyzer(cameraExecutor, analyzer)

                try {
                    cameraProvider.unbindAll()
                    cameraProvider.bindToLifecycle(
                        lifecycleOwner,
                        CameraSelector.DEFAULT_BACK_CAMERA,
                        preview,
                        analysis
                    )
                } catch (e: Exception) {
                    // Camera binding can fail if the lifecycle is already destroyed by the
                    // time this listener runs (e.g. quick navigation away) — nothing to do.
                }
            }, mainExecutor)

            previewView
        }
    )
}

/**
 * Decodes QR codes from CameraX frames with ZXing (plain Java, so no Google Play services on the
 * device or in the dependency tree). Only the Y (luminance) plane of the YUV_420_888 frame is
 * needed; QR decoding is rotation-invariant, so the frame is fed in sensor orientation as is.
 */
private class QrCodeAnalyzer(private val onResult: (String) -> Unit) : ImageAnalysis.Analyzer {

    private val reader = MultiFormatReader().apply {
        setHints(mapOf(DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE)))
    }

    override fun analyze(image: ImageProxy) {
        try {
            val plane = image.planes[0]
            val rowStride = plane.rowStride
            // Rows may be padded past the image width; copy into a buffer sized for the stride
            // so ZXing's row addressing never reads past the end.
            val luminance = ByteArray(rowStride * image.height)
            plane.buffer.let { it.get(luminance, 0, minOf(it.remaining(), luminance.size)) }
            val source = PlanarYUVLuminanceSource(
                luminance, rowStride, image.height, 0, 0, image.width, image.height, false
            )
            val result = reader.decodeWithState(BinaryBitmap(HybridBinarizer(source)))
            result.text?.takeIf { it.isNotEmpty() }?.let(onResult)
        } catch (e: NotFoundException) {
            // No QR code in this frame — the normal case.
        } catch (e: Exception) {
            // Malformed frame or decoder hiccup; skip the frame.
        } finally {
            reader.reset()
            image.close()
        }
    }
}
