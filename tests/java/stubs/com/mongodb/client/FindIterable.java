package com.mongodb.client;

/** Stub di compilazione: com.mongodb.client.FindIterable. */
public interface FindIterable<T> extends MongoIterable<T> {
    FindIterable<T> sort(org.bson.Document sort);

    FindIterable<T> limit(int limit);
}
