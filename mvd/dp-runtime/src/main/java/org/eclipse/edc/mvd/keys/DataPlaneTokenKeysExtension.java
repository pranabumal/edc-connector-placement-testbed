package org.eclipse.edc.mvd.keys;

import org.eclipse.edc.runtime.metamodel.annotation.Extension;
import org.eclipse.edc.runtime.metamodel.annotation.Inject;
import org.eclipse.edc.runtime.metamodel.annotation.Setting;
import org.eclipse.edc.spi.EdcException;
import org.eclipse.edc.spi.security.Vault;
import org.eclipse.edc.spi.system.ServiceExtension;
import org.eclipse.edc.spi.system.ServiceExtensionContext;

import java.security.KeyPairGenerator;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;

/**
 * For PULL transfers the Data Plane signs an access token into each Endpoint
 * Data Reference it hands out, and verifies it on every request to its public
 * endpoint (data-plane-iam). It looks the key pair up in the vault under the
 * two aliases below.
 *
 * This runtime has no external vault, so the pair is generated here at start
 * and put into the in-memory one. Tokens therefore do not outlive a restart of
 * the Data Plane — acceptable for a test environment, where every run starts
 * its transfers afresh; a production deployment keeps the keys in a real vault.
 */
@Extension(value = DataPlaneTokenKeysExtension.NAME)
public class DataPlaneTokenKeysExtension implements ServiceExtension {

    public static final String NAME = "Data Plane token keys (generated at start)";

    @Setting(description = "Vault alias of the private key the Data Plane signs access tokens with", key = "edc.transfer.proxy.token.signer.privatekey.alias")
    private String privateKeyAlias;

    @Setting(description = "Vault alias of the public key the Data Plane verifies access tokens with", key = "edc.transfer.proxy.token.verifier.publickey.alias")
    private String publicKeyAlias;

    @Inject
    private Vault vault;

    @Override
    public String name() {
        return NAME;
    }

    @Override
    public void initialize(ServiceExtensionContext context) {
        try {
            var generator = KeyPairGenerator.getInstance("RSA");
            generator.initialize(2048);
            var pair = generator.generateKeyPair();
            vault.storeSecret(privateKeyAlias, pem("PRIVATE KEY", pair.getPrivate().getEncoded()));
            vault.storeSecret(publicKeyAlias, pem("PUBLIC KEY", pair.getPublic().getEncoded()));
        } catch (NoSuchAlgorithmException e) {
            throw new EdcException("Cannot generate the Data Plane's token key pair", e);
        }
        context.getMonitor().info("Generated the Data Plane's token key pair (aliases '%s', '%s')".formatted(privateKeyAlias, publicKeyAlias));
    }

    private static String pem(String type, byte[] der) {
        var body = Base64.getMimeEncoder(64, "\n".getBytes()).encodeToString(der);
        return "-----BEGIN " + type + "-----\n" + body + "\n-----END " + type + "-----\n";
    }
}
