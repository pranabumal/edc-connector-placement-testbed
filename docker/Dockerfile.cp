# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Build
# All compilation happens inside Docker. No Java or Gradle needed on the host.
# ─────────────────────────────────────────────────────────────────────────────
FROM gradle:9.0-jdk17 AS builder

WORKDIR /app

# Copy Gradle version catalog (layer cached — changes rarely)
COPY gradle/libs.versions.toml gradle/

# Copy build configuration
COPY mvd/settings.gradle.kts ./settings.gradle.kts
COPY mvd/mvd-connector/build.gradle.kts mvd/mvd-connector/build.gradle.kts
COPY mvd/cp-runtime/build.gradle.kts mvd/cp-runtime/build.gradle.kts
COPY mvd/dp-runtime/build.gradle.kts mvd/dp-runtime/build.gradle.kts
COPY mvd/cp-runtime/src mvd/cp-runtime/src

# Download all dependencies (cached layer — only re-runs when build.gradle.kts changes)
RUN gradle :mvd:cp-runtime:dependencies --no-daemon -q 2>/dev/null || true

# Build the fat JAR
RUN gradle :mvd:cp-runtime:shadowJar --no-daemon -q

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Runtime
# Lean JRE-only image (~100 MB vs ~600 MB for the builder stage).
# ─────────────────────────────────────────────────────────────────────────────
FROM eclipse-temurin:17-jre-jammy

WORKDIR /app
COPY --from=builder /app/mvd/cp-runtime/build/libs/cp-connector.jar cp-connector.jar

# Config is mounted at runtime via docker-compose volumes.
# Pass -Dedc.fs.config and -jar as docker-compose command args.
ENTRYPOINT ["java"]
CMD ["-jar", "/app/cp-connector.jar"]
