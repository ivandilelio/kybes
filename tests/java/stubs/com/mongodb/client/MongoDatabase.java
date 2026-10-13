package com.mongodb.client;

/** Stub di compilazione: com.mongodb.client.MongoDatabase. */
public interface MongoDatabase {
    String getName();

    MongoCollection<org.bson.Document> getCollection(String name);

    void createCollection(String name);

    void drop();
}
