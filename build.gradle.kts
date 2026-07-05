
buildscript {
    repositories {
        google()
        mavenCentral()
        maven("https://chaquo.com/maven")
    }
    dependencies {
        classpath("com.android.tools.build:gradle:8.2.2")
        classpath("com.chaquo.python:gradle:15.0.1")
    }
}
plugins {
    id("com.android.application") version "8.2.0" apply false
    id("com.chaquo.python") version "17.0.0" apply false
}
allprojects {
    repositories {
        google()
        mavenCentral()

    }
}