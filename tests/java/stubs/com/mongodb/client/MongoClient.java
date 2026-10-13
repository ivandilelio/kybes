package com.mongodb.client;

/** Stub di compilazione: com.mongodb.client.MongoClient. */
public interface MongoClient extends AutoCloseable {
    MongoDatabase getDatabase(String name);

    ClientSession startSession();

    @Override
    void close();
}
