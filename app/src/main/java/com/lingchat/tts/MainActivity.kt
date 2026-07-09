package com.lingchat.tts

import android.content.Context
import android.content.SharedPreferences
import android.os.Bundle
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.AndroidPlatform
import com.chaquo.python.Python
import kotlinx.coroutines.*
import java.io.File
import java.io.FileOutputStream

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "SBV2TTS"
        private const val PREFS_NAME = "sbv2_prefs"
        private const val KEY_MODEL_VERSION = "model_version"
        private const val CURRENT_MODEL_VERSION = 1 // ⚠️ 模型更新时递增此值
        private const val ASSET_MODEL_DIR = "sbv2_android"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main) // 请确保布局中包含加载提示UI

        CoroutineScope(Dispatchers.Main).launch {
            try {
                // 1. 异步解压模型（避免阻塞主线程）
                val modelDir = withContext(Dispatchers.IO) {
                    prepareModelDir(this@MainActivity)
                }

                // 2. 初始化 ChaquoPy 并注入环境变量
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(this@MainActivity))
                }
                val py = Python.getInstance()
                py.getModule("os").getAttr("environ")
                    .callAttr("__setitem__", "SBV2_MODEL_DIR", modelDir.absolutePath)

                Log.i(TAG, "✅ Model dir injected: ${modelDir.absolutePath}")

                // 3. 启动 TTS 服务
                withContext(Dispatchers.IO) {
                    py.getModule("tts_server")
                }

                // TODO: 更新UI，显示服务已就绪或获取本地端口号

            } catch (e: Exception) {
                Log.e(TAG, "❌ Initialization failed", e)
                // TODO: 显示错误信息给用户
            }
        }
    }

    /**
     * 智能解压：仅在首次安装或版本号变更时执行
     */
    private suspend fun prepareModelDir(context: Context): File {
        val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val savedVersion = prefs.getInt(KEY_MODEL_VERSION, 0)
        val destDir = File(context.filesDir, ASSET_MODEL_DIR)

        if (savedVersion == CURRENT_MODEL_VERSION && destDir.exists()) {
            Log.i(TAG, "Model cache valid (v$CURRENT_MODEL_VERSION), skip extraction.")
            return destDir
        }

        Log.i(TAG, "Extracting model assets (v$savedVersion -> v$CURRENT_MODEL_VERSION)...")
        if (destDir.exists()) destDir.deleteRecursively()

        copyAssetFolder(context.assets, ASSET_MODEL_DIR, destDir)

        prefs.edit().putInt(KEY_MODEL_VERSION, CURRENT_MODEL_VERSION).apply()
        Log.i(TAG, "✅ Extraction complete.")
        return destDir
    }

    private fun copyAssetFolder(assetManager: android.content.res.AssetManager,
                                assetPath: String, destDir: File) {
        val entries = assetManager.list(assetPath)
        if (entries.isNullOrEmpty()) {
            // 是文件
            destDir.parentFile?.mkdirs()
            assetManager.open(assetPath).use { input ->
                FileOutputStream(destDir).use { output ->
                    input.copyTo(output)
                }
            }
        } else {
            // 是目录
            destDir.mkdirs()
            for (entry in entries) {
                copyAssetFolder(assetManager, "$assetPath/$entry", File(destDir, entry))
            }
        }
    }
}