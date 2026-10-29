package org.eclipse.edc.mvd.proxy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.Request;
import org.eclipse.edc.http.spi.EdcHttpClient;
import org.eclipse.edc.spi.result.Result;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Reads the Endpoint Data Reference of a transfer from the consumer Control
 * Plane's Management API (GET /v3/edrs/{transferProcessId}/dataaddress) and
 * keeps it, so only the first fetch of a transfer pays for the lookup. A
 * reference the provider no longer accepts is dropped with {@link #forget}.
 */
class EdrLookup {

    record Edr(String endpoint, String authorization) {
    }

    private final String managementUrl;
    private final EdcHttpClient httpClient;
    private final ObjectMapper mapper;
    private final Map<String, Edr> known = new ConcurrentHashMap<>();

    EdrLookup(String managementUrl, EdcHttpClient httpClient, ObjectMapper mapper) {
        this.managementUrl = managementUrl.replaceAll("/+$", "");
        this.httpClient = httpClient;
        this.mapper = mapper;
    }

    Result<Edr> get(String transferProcessId) {
        var cached = known.get(transferProcessId);
        if (cached != null) {
            return Result.success(cached);
        }
        var request = new Request.Builder()
                .url(managementUrl + "/v3/edrs/" + transferProcessId + "/dataaddress")
                .get()
                .build();
        try (var response = httpClient.execute(request)) {
            if (!response.isSuccessful()) {
                return Result.failure("Control Plane answered %d for transfer %s".formatted(response.code(), transferProcessId));
            }
            var json = mapper.readTree(response.body().string());
            var endpoint = property(json, "endpoint");
            var authorization = property(json, "authorization");
            if (endpoint == null || authorization == null) {
                return Result.failure("Endpoint Data Reference of transfer %s has no endpoint or authorization".formatted(transferProcessId));
            }
            var edr = new Edr(endpoint, authorization);
            known.put(transferProcessId, edr);
            return Result.success(edr);
        } catch (IOException e) {
            return Result.failure("Cannot reach the Control Plane: " + e.getMessage());
        }
    }

    void forget(String transferProcessId) {
        known.remove(transferProcessId);
    }

    /** EDC may return a property bare or under its namespace. */
    private static String property(JsonNode json, String name) {
        var keys = json.fieldNames();
        while (keys.hasNext()) {
            var key = keys.next();
            if (key.equals(name) || key.endsWith("/" + name) || key.endsWith(":" + name)) {
                return json.get(key).asText();
            }
        }
        return null;
    }
}
