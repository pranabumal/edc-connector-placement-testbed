plugins {
    `java-library`
    id("application")
    alias(libs.plugins.shadow)
}

// ─────────────────────────────────────────────────────────────────────────────
// Control Plane runtime — no data-plane-core/data-plane-http on the classpath.
// Talks to a remote Data Plane runtime over the data-plane-signaling protocol:
// hosts the selector registry (edc.dpf.selector.url) that the Data Plane
// self-registers into, and calls out to the Data Plane's signaling API to
// start/suspend/terminate transfers.
// ─────────────────────────────────────────────────────────────────────────────
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
    implementation(libs.edc.management.api)

    // Dataspace Protocol (DSP) — contract negotiation between connectors
    implementation(libs.edc.dsp)

    // IAM mock (no real identity provider needed for testing)
    implementation(libs.edc.iam.mock)

    // Data plane selector registry — lives on the Control Plane; the Data
    // Plane runtime registers itself here via edc.dpf.selector.url
    implementation(libs.edc.data.plane.selector.core)
    implementation(libs.edc.data.plane.selector.api)

    // Transfer via data plane signaling — Control Plane side (calls out to a
    // remote Data Plane's signaling API to drive the transfer lifecycle)
    implementation(libs.edc.transfer.data.plane.signaling)
    implementation(libs.edc.data.plane.signaling.client)

    // EDR store — required by EdrCacheApiExtension pulled in via management-api
    implementation(libs.edc.edr.store.core)
    // PULL transfers, consumer side: stores the Endpoint Data Reference
    // (address + access token) a provider sends when a transfer starts, so
    // the consumer can read it from /management/v3/edrs/{transferId}/dataaddress
    implementation(libs.edc.edr.store.receiver)

    // Policy monitor — provider side: keeps re-evaluating the contract policy
    // of running transfers and terminates one when the policy stops holding
    // (e.g. a time-limited contract expires), which makes the Data Plane
    // revoke its access token. In-memory store: a restart forgets what it
    // was watching, which the test runs never rely on.
    implementation(libs.edc.policy.monitor.core)

    // Validation — asset dataAddress schema validation at creation time
    implementation(libs.edc.validator.data.address.http.data)

    // ── SQL persistence — this unit's own Postgres (see deploy/README.md) ──
    implementation(libs.edc.sql.core)
    implementation(libs.edc.sql.bootstrapper)        // edc.sql.schema.autocreate
    implementation(libs.edc.sql.pool.apache.commons) // edc.datasource.default.*
    implementation(libs.edc.sql.lease)
    implementation(libs.edc.transaction.local)
    implementation(libs.postgres)
    implementation(libs.edc.asset.index.sql)
    implementation(libs.edc.contract.definition.store.sql)
    implementation(libs.edc.contract.negotiation.store.sql)
    implementation(libs.edc.policy.definition.store.sql)
    implementation(libs.edc.transfer.process.store.sql)
    implementation(libs.edc.data.plane.instance.store.sql)
    implementation(libs.edc.edr.index.sql)
}

application {
    mainClass.set("org.eclipse.edc.boot.system.runtime.BaseRuntime")
}

tasks.withType<com.github.jengelman.gradle.plugins.shadow.tasks.ShadowJar> {
    mergeServiceFiles()
    archiveFileName.set("cp-connector.jar")
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}
