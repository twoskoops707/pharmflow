plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.pharmflow.scorecard"
    compileSdk = 34

    defaultConfig {
        // Keep the original applicationId across the CPharm -> PharmFlow rebrand:
        // this is the installed package identity, and changing it makes Android
        // treat an upgrade as a brand-new app -- existing users would lose their
        // scorecard preferences/server URL and end up with two installed apps.
        // namespace above carries the new branding; that's purely a compile-time
        // Kotlin/R-class package and safe to differ from applicationId.
        applicationId = "com.cpharm.scorecard"
        minSdk = 24
        targetSdk = 34
        versionCode = 4
        versionName = "2.0.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
}

