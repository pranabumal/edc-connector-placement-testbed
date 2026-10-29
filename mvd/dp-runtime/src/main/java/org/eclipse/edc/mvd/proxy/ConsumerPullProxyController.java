package org.eclipse.edc.mvd.proxy;

import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.container.AsyncResponse;
import jakarta.ws.rs.container.Suspended;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.core.StreamingOutput;
import org.eclipse.edc.connector.dataplane.spi.pipeline.PipelineService;
import org.eclipse.edc.connector.dataplane.spi.pipeline.StreamFailure;
import org.eclipse.edc.connector.dataplane.spi.response.TransferErrorResponse;
import org.eclipse.edc.connector.dataplane.util.sink.AsyncStreamingDataSink;
import org.eclipse.edc.spi.monitor.Monitor;
import org.eclipse.edc.spi.types.domain.DataAddress;
import org.eclipse.edc.spi.types.domain.transfer.DataFlowStartMessage;
import org.eclipse.edc.spi.types.domain.transfer.FlowType;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;

import static jakarta.ws.rs.core.MediaType.APPLICATION_JSON;
import static jakarta.ws.rs.core.MediaType.WILDCARD;
import static jakarta.ws.rs.core.Response.Status.BAD_GATEWAY;
import static jakarta.ws.rs.core.Response.Status.FORBIDDEN;
import static jakarta.ws.rs.core.Response.Status.INTERNAL_SERVER_ERROR;
import static jakarta.ws.rs.core.Response.Status.NOT_FOUND;
import static org.eclipse.edc.spi.constants.CoreConstants.EDC_NAMESPACE;

/**
 * GET {proxy}/{transferProcessId}: fetches the data of a started PULL transfer
 * from the provider's Data Plane and streams it to the caller.
 */
@Path("/{transferProcessId}")
@Produces(WILDCARD)
public class ConsumerPullProxyController {

    private final PipelineService pipelineService;
    private final EdrLookup edrs;
    private final ExecutorService executorService;
    private final Monitor monitor;

    public ConsumerPullProxyController(PipelineService pipelineService, EdrLookup edrs, ExecutorService executorService, Monitor monitor) {
        this.pipelineService = pipelineService;
        this.edrs = edrs;
        this.executorService = executorService;
        this.monitor = monitor;
    }

    @GET
    public void get(@PathParam("transferProcessId") String transferProcessId, @Suspended AsyncResponse response) {
        var edr = edrs.get(transferProcessId);
        if (edr.failed()) {
            response.resume(error(NOT_FOUND, edr.getFailureMessages()));
            return;
        }

        // The provider's Data Plane as an HttpData source: data-plane-http
        // sends authKey: authCode as a request header
        var source = DataAddress.Builder.newInstance()
                .type("HttpData")
                .property(EDC_NAMESPACE + "baseUrl", edr.getContent().endpoint())
                .property(EDC_NAMESPACE + "authKey", "Authorization")
                .property(EDC_NAMESPACE + "authCode", edr.getContent().authorization())
                .build();
        var request = DataFlowStartMessage.Builder.newInstance()
                .id(UUID.randomUUID().toString())
                .processId(transferProcessId)
                .sourceDataAddress(source)
                .destinationDataAddress(DataAddress.Builder.newInstance().type(AsyncStreamingDataSink.TYPE).build())
                .flowType(FlowType.PULL)
                .build();

        AsyncStreamingDataSink.AsyncResponseContext responseContext = callback -> {
            StreamingOutput output = stream -> callback.outputStreamConsumer().accept(stream);
            return response.resume(Response.ok(output).type(callback.mediaType()).build());
        };

        pipelineService.transfer(request, new AsyncStreamingDataSink(responseContext, executorService))
                .whenComplete((result, throwable) -> {
                    if (throwable != null) {
                        response.resume(error(INTERNAL_SERVER_ERROR, List.of("Transfer failed: " + throwable.getMessage())));
                    } else if (result.failed()) {
                        var reason = result.getFailure().getReason();
                        if (reason == StreamFailure.Reason.NOT_AUTHORIZED) {
                            // the provider revoked the token (e.g. the contract expired): ask the Control Plane again next time
                            edrs.forget(transferProcessId);
                            monitor.info("Provider refused transfer %s: %s".formatted(transferProcessId, result.getFailureDetail()));
                            response.resume(error(FORBIDDEN, result.getFailureMessages()));
                        } else if (reason == StreamFailure.Reason.NOT_FOUND) {
                            response.resume(error(NOT_FOUND, result.getFailureMessages()));
                        } else {
                            response.resume(error(BAD_GATEWAY, result.getFailureMessages()));
                        }
                    }
                });
    }

    private static Response error(Response.Status status, List<String> errors) {
        return Response.status(status).type(APPLICATION_JSON).entity(new TransferErrorResponse(errors)).build();
    }
}
