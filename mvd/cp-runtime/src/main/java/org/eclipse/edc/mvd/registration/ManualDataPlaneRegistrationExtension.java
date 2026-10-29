package org.eclipse.edc.mvd.registration;

import org.eclipse.edc.connector.dataplane.selector.spi.DataPlaneSelectorService;
import org.eclipse.edc.connector.dataplane.selector.spi.instance.DataPlaneInstance;
import org.eclipse.edc.connector.dataplane.selector.spi.store.DataPlaneInstanceStore;
import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.runtime.metamodel.annotation.Setting;
import org.eclipse.edc.spi.EdcException;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * EDC 0.14.1 can register a separate Data Plane over HTTP: the Data Plane's
 * data-plane-self-registration calls a remote DataPlaneSelectorService
 * (data-plane-selector-client), which posts to the Control Plane's
 * data-plane-selector-control-api. This testbed does not use that path.
 *
 * This extension runs on the Control Plane instead and registers a remote
 * Data Plane's known, static capabilities (HttpData source/sink via
 * data-plane-http) directly against the in-process selector service. No
 * network call happens here — the CP only calls out to the registered URL
 * later, when a transfer actually starts.
 *
 * addInstance() always inserts the instance in REGISTERED state; EDC's own
 * background state machine is supposed to promote it to AVAILABLE by polling
 * GET {instance.url}/check. That endpoint 404s in this build (an apparent
 * EDC 0.14.1 routing issue on DataPlaneSignalingApiController — POST start
 * and GET {id}/state on the same controller both route correctly, only
 * /check doesn't), which would otherwise leave the instance permanently
 * unselectable ("No dataplane found"). Force-promoting the instance here and
 * re-affirming it on a short interval sidesteps that regardless of cause.
 */
@Extension(value = ManualDataPlaneRegistrationExtension.NAME)
public class ManualDataPlaneRegistrationExtension implements ServiceExtension {

    public static final String NAME = "Manual Remote Data Plane Registration";

    @Setting(description = "Base control-context URL of the remote Data Plane runtime (its web.http.control host:port/path)", key = "edc.dataplane.remote.control.url")
    private String remoteControlUrl;

    @Setting(description = "Identifier to register the remote Data Plane instance under", key = "edc.dataplane.remote.id", defaultValue = "remote-dataplane")
    private String remoteId;

    @Inject
    private DataPlaneSelectorService dataPlaneSelectorService;

    @Inject
    private DataPlaneInstanceStore dataPlaneInstanceStore;

    private ServiceExtensionContext context;
    private ScheduledExecutorService scheduler;

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public void initialize(ServiceExtensionContext context) {
        this.context = context;
    }

    @Override
    public void start() {
        var monitor = context.getMonitor().withPrefix("ManualDataPlaneRegistration");

        var instance = DataPlaneInstance.Builder.newInstance()
                .id(remoteId)
                .url(remoteControlUrl + "/v1/dataflows")
                .allowedSourceType("HttpData")
                .allowedTransferType("HttpData-PUSH")
                .allowedTransferType("HttpData-PULL")
                .build();

        // The data-plane instance store is persistent (SQL), and addInstance
        // does not change the URL of an instance that already exists. When the
        // Data Plane has moved (e.g. to another machine), the stored instance
        // would keep pointing at the old address — so replace it.
        var existing = dataPlaneInstanceStore.findById(remoteId);
        if (existing != null && !String.valueOf(instance.getUrl()).equals(String.valueOf(existing.getUrl()))) {
            monitor.info("Replacing data plane '%s' registered at %s".formatted(remoteId, existing.getUrl()));
            dataPlaneSelectorService.delete(remoteId)
                    .orElseThrow(f -> new EdcException("Cannot replace remote data plane: " + f.getFailureDetail()));
        }

        dataPlaneSelectorService.addInstance(instance)
                .onSuccess(it -> monitor.info("Registered remote data plane '%s' at %s".formatted(remoteId, instance.getUrl())))
                .orElseThrow(f -> new EdcException("Cannot register remote data plane: " + f.getFailureDetail()));

        scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            var t = new Thread(r, "manual-dataplane-registration-keepalive");
            t.setDaemon(true);
            return t;
        });
        scheduler.scheduleAtFixedRate(() -> keepAvailable(monitor), 0, 15, TimeUnit.SECONDS);
    }

    @Override
    public void shutdown() {
        if (scheduler != null) {
            scheduler.shutdownNow();
        }
    }

    private void keepAvailable(org.eclipse.edc.spi.monitor.Monitor monitor) {
        var current = dataPlaneInstanceStore.findById(remoteId);
        if (current == null) {
            return;
        }
        current.transitionToAvailable();
        dataPlaneInstanceStore.save(current);
        monitor.debug("Re-affirmed remote data plane '%s' as AVAILABLE".formatted(remoteId));
    }
}
