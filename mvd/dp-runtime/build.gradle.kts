plugins {
    `java-library`
    id("application")
    alias(libs.plugins.shadow)
}

// ─────────────────────────────────────────────────────────────────────────────
// Data Plane runtime — no control-plane-core/management-api/dsp on the
// classpath. The Control Plane registers it in its selector registry (see
// cp-runtime's ManualDataPlaneRegistrationExtension), and it exposes the
// data-plane-signaling API so the Control Plane can start/suspend/terminate transfers on this runtime.
// ─────────────────────────────────────────────────────────────────────────────
dependencies {
    // Core runtime
    implementation(libs.edc.boot)
    implementation(libs.edc.runtime.core)
    implementation(libs.edc.connector.core)
    implementation(libs.edc.configuration.filesystem)
    implementation(libs.edc.http)

    // IAM mock — identity on the signaling/control channel. Consumer-facing
    // PULL requests are authorised by the Data Plane's own access tokens
    // (data-plane-iam, below), not by this
    implementation(libs.edc.iam.mock)

    // Control context — hosts the data-plane-signaling API's inbound endpoints
    // (web.http.control.*); this Data Plane has no Control Plane extensions,
    // it only needs the context/port binding itself
    implementation(libs.edc.control.api.configuration)
    implementation(libs.edc.api.core)          // provides ApiAuthenticationRegistry
    implementation(libs.edc.json.ld)           // provides JsonLd

    // Client the Data Plane uses to report transfer status back to the
    // Control Plane's Transfer Process Manager
    implementation(libs.edc.control.plane.api.client)

    // Data Plane
    implementation(libs.edc.data.plane.core)
    implementation(libs.edc.data.plane.http)
    // PULL transfers: the public endpoint consumers fetch from, and the access
    // tokens that guard it. The token key pair comes from this runtime's
    // DataPlaneTokenKeysExtension (generated at start, in-memory vault)
    implementation(libs.edc.data.plane.public.api)
    implementation(libs.edc.data.plane.iam)
    implementation(libs.edc.token.core)
    // Consumer pull proxy (this runtime's ConsumerPullProxyExtension): the
    // consumer's Data Plane fetches from the provider's Data Plane through
    // its own transfer pipeline and streams the data to the caller
    implementation(libs.edc.data.plane.spi)
    implementation(libs.edc.data.plane.util)
    implementation(libs.edc.http.spi)
    implementation(libs.edc.web.spi)
    implementation(libs.jakarta.rsApi)
    //
    // data-plane-self-registration is NOT used here. EDC 0.14.1 can register a
    // separate Data Plane over HTTP (data-plane-selector-client on the Data
    // Plane, data-plane-selector-control-api on the Control Plane), but this
    // testbed registers it from the Control Plane side instead (see
    // cp-runtime's ManualDataPlaneRegistrationExtension).

    // Data plane signaling API — exposed by the Data Plane so a remote
    // Control Plane can drive the transfer lifecycle over HTTP
    implementation(libs.edc.data.plane.signaling.api)

    // Validation — HttpData address resolution when fetching/pushing data
    implementation(libs.edc.validator.data.address.http.data)

    // ── SQL persistence — this unit's own Postgres (see deploy/README.md) ──
    implementation(libs.edc.sql.core)
    implementation(libs.edc.sql.bootstrapper)        // edc.sql.schema.autocreate
    implementation(libs.edc.sql.pool.apache.commons) // edc.datasource.default.*
    implementation(libs.edc.sql.lease)
    implementation(libs.edc.transaction.local)
    implementation(libs.postgres)
    implementation(libs.edc.data.plane.store.sql)
    implementation(libs.edc.accesstokendata.store.sql)
}

application {
    mainClass.set("org.eclipse.edc.boot.system.runtime.BaseRuntime")
}

tasks.withType<com.github.jengelman.gradle.plugins.shadow.tasks.ShadowJar> {
    mergeServiceFiles()
    archiveFileName.set("dp-connector.jar")
    duplicatesStrategy = DuplicatesStrategy.INCLUDE
}
