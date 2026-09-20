import groovy.json.JsonSlurper
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

base {
    // Flavor name is inserted automatically: musikster-nils-release.apk etc.
    archivesName.set("musikster")
}

/**
 * One product flavor per recipient, discovered from people/<slug>/person.json (see
 * README.md "Adding a person"). The slug doubles as the flavor name and the deck id.
 * Everything about a person lives in that one directory — config, photo, the deck.json
 * scripts/build_deck.py generates (people/<slug>/assets/, wired in below as the flavor's
 * assets dir so it gets bundled) and the printable PDFs — so it can be its own private
 * git repo. Adding someone is a new directory rather than a Gradle edit.
 *
 * people/ is gitignored (it's personal data and the repo is public), so a fresh clone or
 * CI has no people at all. In that case a single generic "musikster" flavor is built: no
 * greeting, no bundled deck, any deck can be imported from Home. Personal builds are
 * made locally, where people/ exists.
 */
data class Person(
    val slug: String,
    val appName: String,
    val greeting: String,
    val palette: List<String>,
    /** people/<slug>, or null for the generic fallback flavor. */
    val dir: File?,
)

fun loadPeople(): List<Person> {
    val peopleDir = rootProject.file("people")
    val dirs = peopleDir.listFiles { f -> f.isDirectory && File(f, "person.json").isFile }
        ?.sortedBy { it.name } ?: emptyList()
    if (dirs.isEmpty()) {
        logger.lifecycle("No people/<slug>/person.json found — building the generic 'musikster' flavor only.")
        return listOf(Person(slug = "musikster", appName = "Musikster", greeting = "", palette = emptyList(), dir = null))
    }
    return dirs.map { dir ->
        val slug = dir.name
        check(slug.matches(Regex("[a-z][a-z0-9]*"))) {
            "people/$slug: slug must be lowercase letters/digits (it becomes a Gradle flavor name)."
        }
        @Suppress("UNCHECKED_CAST")
        val json = JsonSlurper().parse(File(dir, "person.json")) as Map<String, Any?>
        Person(
            slug = slug,
            appName = json["appName"] as? String ?: "${json["name"]}'s Musikster",
            greeting = json["greeting"] as? String ?: "",
            palette = (json["palette"] as? List<*>)?.map { it.toString() } ?: emptyList(),
            dir = dir,
        )
    }
}

/** Escapes a Kotlin string for use as an Android <string> resource value. */
fun androidStringResource(value: String): String = value
    .replace("\\", "\\\\")
    .replace("'", "\\'")
    .replace("\"", "\\\"")
    .replace("\n", "\\n")
    .replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")

android {
    namespace = "de.powerizzle.musikster"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "de.powerizzle.musikster"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("release") {
            // Read from environment variables — set locally or via GitHub Secrets in CI.
            val keystorePath = System.getenv("KEYSTORE_PATH")
            if (keystorePath != null) {
                storeFile     = file(keystorePath)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias      = System.getenv("KEY_ALIAS")
                keyPassword   = System.getenv("KEY_PASSWORD")
            }
        }
    }

    val people = loadPeople()
    flavorDimensions += "person"
    productFlavors {
        people.forEach { person ->
            create(person.slug) {
                dimension = "person"
                // Deliberately no applicationIdSuffix: every flavor shares the one package
                // name registered in the Spotify dashboard (package + signing SHA-1), so a new
                // person doesn't need a new Spotify registration. Trade-off: only one
                // person's build can be installed on a given phone at a time.
                resValue("string", "app_name", androidStringResource(person.appName))
                resValue("string", "greeting", androidStringResource(person.greeting))
                buildConfigField("String", "PERSON_ID", "\"${person.slug}\"")
                buildConfigField(
                    "String", "CARD_PALETTE",
                    "\"${person.palette.joinToString(",")}\""
                )
            }
        }
    }
    sourceSets {
        people.forEach { person ->
            // The generated deck.json lives with the rest of the person's data rather than
            // under app/src/<slug>/, so the whole person is one directory (and one repo).
            person.dir?.let { getByName(person.slug).assets.srcDir(File(it, "assets")) }
        }
    }

    buildTypes {
        release {
            signingConfig   = signingConfigs.getByName("release")
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
        buildConfig = true
        resValues = true // per-flavor app_name/greeting come from resValue() above
    }

    defaultConfig {
        // CI (see .github/workflows/build.yml) sets this via the SPOTIFY_CLIENT_ID repo secret;
        // local Android Studio builds fall back to local.properties.
        val spotifyClientId = System.getenv("SPOTIFY_CLIENT_ID")
            ?: localProperties.getProperty("SPOTIFY_CLIENT_ID", "")
        buildConfigField("String", "SPOTIFY_CLIENT_ID", "\"$spotifyClientId\"")
    }
}

dependencies {
    // Spotify App Remote SDK — download from https://github.com/spotify/android-sdk/releases
    // and place the .aar in app/libs/ (see README.md).
    implementation(files("libs/spotify-app-remote-release-0.8.0.aar"))
    implementation(libs.gson)

    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.kotlinx.coroutines.android)

    // QR decoding: ZXing core is plain Java with no Google Play services dependency.
    implementation(libs.zxing.core)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
}
