# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.kts.

# Keep Chaquopy Python classes
-keep class com.chaquo.python.** { *; }

# Keep TTS server class
-keep class com.stbvs22.tts.** { *; }

# Keep FastAPI/Pydantic serialization
-keep class pydantic.** { *; }
-dontwarn pydantic.**

# Keep uvicorn
-dontwarn uvicorn.**
-dontwarn multipart.**
