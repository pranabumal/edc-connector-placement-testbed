plugins {
    `java-library`
    id("application")
    alias(libs.plugins.shadow)
}

dependencies {
    // Core runtime
    implementation(libs.edc.boot)
    implementation(libs.edc.runtime.core)
    implementation(libs.edc.connector.core)
    implementation(libs.edc.configuration.filesystem)
    implementation(libs.edc.http)

    // Control Plane
    implementation(libs.edc.control.plane.core)
    implementation(libs.edc.control.plane.api)
    implementation(libs.edc.control.api.configuration)
    implementation(libs.edc.control.plane.api.client)
    implementation(libs.edc.management.api)

    // Dataspace Protocol (DSP) — contract negotiation between connectors
    implementation(libs.edc.dsp)

    // IAM mock (no real identity provider needed for testing)
    implementation(libs.edc.iam.mock)

    // Data Plane
    implementation(libs.edc.data.plane.core)
    implementation(libs.edc.data.plane.http)
    // edc-data-plane-iam omitted: requires real key vault + token infra;
    // iam-mock covers identity for this test environment (PUSH transfers only)
    implementation(libs.edc.data.plane.selector.core)
    implementation(libs.edc.data.plane.selector.api)
    implementation(libs.edc.data.plane.self.registration)

    // Transfer via data plane signaling
    implementation(libs.edc.transfer.data.plane.signaling)
    implementation(libs.edc.data.plane.signaling.api)
    implementation(libs.edc.data.plane.signaling.client)

    // EDR store — required by EdrCacheApiExtension pulled in via management-api
    implementation(libs.edc.edr.store.core)

    // Validation
    implementation(libs.edc.validator.data.address.http.data)
}

application {
    mainClass.set("org.eclipse.edc.boot.system.runtime.BaseRuntime")
}

tasks.withType<com.github.jengelman.gradle.plugins.shadow.tasks.ShadowJar> {
    mergeServiceFiles()
    archiveFileName.set("connector.jar")
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}
