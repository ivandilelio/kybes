package com.mongodb.client;

/** Stub di compilazione: com.mongodb.client.MongoIterable. */
public interface MongoIterable<T> extends Iterable<T> {
    T first();

    <A extends java.util.Collection<? super T>> A into(A target);
}
