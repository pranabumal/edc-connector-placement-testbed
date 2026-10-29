package org.eclipse.edc.mvd.proxy;

import org.eclipse.edc.connector.dataplane.spi.pipeline.PipelineService;
import org.eclipse.edc.http.spi.EdcHttpClient;
import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.runtime.metamodel.annotation.Setting;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;
import org.eclipse.edc.spi.types.TypeManager;
import org.eclipse.edc.web.spi.WebService;
import org.eclipse.edc.web.spi.configuration.PortMapping;
import org.eclipse.edc.web.spi.configuration.PortMappingRegistry;

import java.util.concurrent.Executors;

/**
 * Puts the consumer's Data Plane on the data path of a PULL transfer.
 *
 * In EDC 0.14.1 a consumer-side Data Plane is only asked to provision a
 * destination (DataPlaneManager.provision); it never moves data. In a PULL
 * transfer the consumer's Control Plane receives the Endpoint Data Reference
 * (the provider Data Plane's address and an access token) and whoever holds it
 * fetches from the provider's Data Plane directly. EDC leaves the consumer
 * side of that to the deployment (its own HTTP proxy, data-plane-public-api-v2,
 * is deprecated with the note to "provide an alternative implementation").
 *
 * This extension is such an implementation, after the model of Tractus-X EDC's
 * edc-dataplane-proxy-consumer-api: a consumer application calls
 *
 *     GET {proxy}/{transferProcessId}
 *
 * on its own Data Plane, which looks the Endpoint Data Reference up on its own
 * Control Plane, fetches the data from the provider's Data Plane through its
 * normal transfer pipeline (data-plane-http source) and streams it back. The
 * application never sees the access token, and the data travels provider Data
 * Plane to consumer Data Plane.
 *
 * Unlike the Tractus-X extension it reads the reference over the Control
 * Plane's Management API instead of from a shared database, because here every
 * unit has its own database.
 *
 * Active only when edc.mvd.consumer.proxy.management.url is set, so the
 * provider's Data Plane (same runtime image) does not expose it.
 */
@Extension(value = ConsumerPullProxyExtension.NAME)
public class ConsumerPullProxyExtension implements ServiceExtension {

    public static final String NAME = "Consumer pull proxy";
    static final String CONTEXT = "proxy";
    private static final int THREAD_POOL = 10;

    @Setting(description = "Management API base URL of this consumer's Control Plane (e.g. http://host:9192/management); the proxy is off when unset", key = "edc.mvd.consumer.proxy.management.url", required = false)
    private String managementUrl;

    @Setting(description = "Port of the consumer pull proxy", key = "web.http." + CONTEXT + ".port", defaultValue = "9296")
    private int port;

    @Setting(description = "Path of the consumer pull proxy", key = "web.http." + CONTEXT + ".path", defaultValue = "/proxy")
    private String path;

    @Inject
    private PortMappingRegistry portMappingRegistry;
    @Inject
    private WebService webService;
    @Inject
    private PipelineService pipelineService;
    @Inject
    private EdcHttpClient httpClient;
    @Inject
    private TypeManager typeManager;

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public void initialize(ServiceExtensionContext context) {
        var monitor = context.getMonitor();
        if (managementUrl == null || managementUrl.isBlank()) {
            monitor.info("Consumer pull proxy is off (edc.mvd.consumer.proxy.management.url not set)");
            return;
        }
        portMappingRegistry.register(new PortMapping(CONTEXT, port, path));
        var edrs = new EdrLookup(managementUrl, httpClient, typeManager.getMapper());
        var executor = Executors.newFixedThreadPool(THREAD_POOL);
        webService.registerResource(CONTEXT, new ConsumerPullProxyController(pipelineService, edrs, executor, monitor));
        monitor.info("Consumer pull proxy on port %d, path %s, Endpoint Data References from %s".formatted(port, path, managementUrl));
    }
}
