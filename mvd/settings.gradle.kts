
pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        mavenCentral()
        mavenLocal()
    }
}

include(":mvd:mvd-connector")
include(":mvd:cp-runtime")
include(":mvd:dp-runtime")