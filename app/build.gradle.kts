plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "com.stbvs22.tts"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.stbvs22.tts"
        minSdk = 26  // Android 8.0 (needed for foreground service)
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"

        ndk {
            // Only build for 64-bit ARM (most modern Android devices)
            abiFilters += listOf("arm64-v8a")
        }

    }
    buildTypes {
        release {
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

    // Copy style_bert_vits2 package from the sibling stbvs22 directory
    // into the Python source directory for bundling in the APK.
    // Disabled by default; enable when the source project is available.
    sourceSets {
        // getByName("main") {
        //     python {
        //         srcDirs("src/main/python")
        //     }
        // }
    }
}
chaquopy {
    defaultConfig {
        buildPython("C:/Users/ly/AppData/Local/Programs/Python/Python310/python.exe")
        pip{
            // Install dependencies from requirements file
            options("--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple")
            install("-r", "D:/stbvs22-android/app/src/main/python/requirements_chaquopy.txt")

            // Uncomment and point to your PyTorch Android wheel if available:
            // install("/path/to/torch-2.x.0-cp311-cp311-linux_aarch64.whl")
        }
    }
}
dependencies {
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("com.google.android.material:material:1.11.0")
}

// -------------------------------------------------------------------
// Helper task: Copy style_bert_vits2 from ../stbvs22 for APK bundling
// Enable with: ./gradlew copyStyleBert -Pstbvs22Dir=../stbvs22
// -------------------------------------------------------------------
tasks.register<Copy>("copyStyleBert") {
    val srcDir = project.findProperty("stbvs22Dir")?.toString() ?: "../stbvs22"
    from("$srcDir/style_bert_vits2") {
        include("**/*.py")
        include("**/*.json")
        include("**/*.bin")
        include("**/*.txt")
    }
    into("src/main/python/style_bert_vits2")
    includeEmptyDirs = false
    doLast {
        println("Copied style_bert_vits2 package to src/main/python/")
    }
}
