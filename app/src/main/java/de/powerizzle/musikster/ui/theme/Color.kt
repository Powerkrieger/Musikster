package de.powerizzle.musikster.ui.theme

import androidx.compose.ui.graphics.Color
import de.powerizzle.musikster.BuildConfig

// Material accent colors. Mostly moot: MusiksterTheme uses dynamic (wallpaper) color on
// Android 12+, so these only show on older devices. The visible per-person color is the
// card-background palette below.
val Purple80 = Color(0xFFD0BCFF)
val PurpleGrey80 = Color(0xFFCCC2DC)
val Pink80 = Color(0xFFEFB8C8)

val Purple40 = Color(0xFF6650a4)
val PurpleGrey40 = Color(0xFF625b71)
val Pink40 = Color(0xFF7D5260)

private val DefaultCardBackgroundPalette = listOf(
    0xFFC2185B, // pink
    0xFF6A1B9A, // purple
    0xFF1565C0, // blue
    0xFF00695C, // teal
    0xFFE65100, // orange
    0xFF2E7D32, // green
)

/**
 * Packed ARGB colors a per-round background gradient is drawn from (two picked at random
 * each round, see MainViewModel). Comes from the flavor's person.json "palette" (RRGGBB hex
 * strings, via BuildConfig); falls back to the default set if fewer than two are given.
 */
val CardBackgroundPalette: List<Long> = BuildConfig.CARD_PALETTE
    .split(",")
    .map { it.trim().removePrefix("#") }
    .filter { it.matches(Regex("[0-9A-Fa-f]{6}")) }
    .map { ("FF$it").toLong(16) }
    .takeIf { it.size >= 2 }
    ?: DefaultCardBackgroundPalette
