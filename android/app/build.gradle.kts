plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// Server URL baked into the APK so users never have to type it.
// CI passes it from the HINDIDUB_SERVER_URL repository variable.
val serverUrl: String = (System.getenv("HINDIDUB_SERVER_URL")
    ?: (project.findProperty("hindidub.serverUrl") as String?)
    ?: "https://YOUR-HF-USERNAME-hindidub.hf.space").trimEnd('/')

val keystorePath: String? = System.getenv("KEYSTORE_PATH")

android {
    namespace = "com.hindidub.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.hindidub.app"
        minSdk = 29
        targetSdk = 35
        versionCode = (System.getenv("VERSION_CODE") ?: "1").toInt()
        versionName = System.getenv("VERSION_NAME") ?: "1.0.0"
        buildConfigField("String", "DEFAULT_SERVER_URL", "\"$serverUrl\"")
    }

    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KEY_ALIAS")
                keyPassword = System.getenv("KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // Without a keystore the release APK is signed with the debug key so it still installs.
            signingConfig = if (keystorePath != null) signingConfigs.getByName("release")
            else signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime)
    implementation(libs.androidx.lifecycle.viewmodel)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons)
    implementation(libs.androidx.work)
    implementation(libs.androidx.splash)
    implementation(libs.okhttp)
    implementation(libs.media3.exoplayer)
    implementation(libs.media3.ui)
}
