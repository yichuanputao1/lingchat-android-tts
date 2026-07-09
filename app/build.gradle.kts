plugins {
    id 'com.android.application'
    id 'com.chaquo.python' version '16.0.0' // 请使用最新版本
}

android {
    compileSdk 34
    defaultConfig {
        applicationId "com.example.sbv2tts"
        minSdk 24
        targetSdk 34

        ndk {
            abiFilters 'arm64-v8a', 'x86_64' // 仅保留主流架构以减小体积
        }
    }

    // ⚠️ 关键：防止大模型文件被 AAPT 压缩，加快解压速度
    aaptOptions {
        noCompress "onnx", "txt", "bin"
    }
}

chaquopy {
    defaultConfig {
        pip {
            install("sherpa-onnx==1.10.+") // 锁定兼容版本
            install("fastapi==0.115.+")
            install("uvicorn[standard]==0.34.+")
            // ❌ 绝对不要安装: torch, transformers, onnxruntime, soundfile
        }
    }
}

dependencies {
    implementation 'androidx.appcompat:appcompat:1.7.0'
    implementation 'org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0'
}