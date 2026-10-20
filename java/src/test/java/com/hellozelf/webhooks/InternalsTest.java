package com.hellozelf.webhooks;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

/** The package private helpers behind verification. */
class InternalsTest {

    @Test
    void aMalformedHexDigestIsRejected() {
        assertNull(Webhook.fromHex("odd"));
        assertNull(Webhook.fromHex("zz"));
        assertNotNull(Webhook.fromHex("00ff"));
    }

    @Test
    void secretsOfBuildsAList() {
        assertEquals(2, Webhook.secretsOf("a", "b").size());
    }
}
