package com.mongodb.client;

/** Stub di compilazione: com.mongodb.client.ClientSession. */
public interface ClientSession extends AutoCloseable {
    <T> T withTransaction(TransactionBody<T> body);

    @Override
    void close();
}
