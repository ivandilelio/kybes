package com.mongodb.client;

import com.mongodb.client.model.CountOptions;
import com.mongodb.client.model.FindOneAndUpdateOptions;
import com.mongodb.client.model.IndexOptions;
import org.bson.Document;

/** Stub di compilazione: com.mongodb.client.MongoCollection. */
public interface MongoCollection<T> {
    FindIterable<T> find(Document filter);

    FindIterable<T> find(ClientSession session, Document filter);

    long countDocuments();

    long countDocuments(Document filter, CountOptions options);

    long countDocuments(ClientSession session, Document filter, CountOptions options);

    void insertOne(T doc);

    void insertOne(ClientSession session, T doc);

    void replaceOne(Document filter, T doc);

    void replaceOne(ClientSession session, Document filter, T doc);

    void updateMany(Document filter, Document update);

    void updateMany(ClientSession session, Document filter, Document update);

    void deleteOne(Document filter);

    void deleteOne(ClientSession session, Document filter);

    T findOneAndUpdate(Document filter, Document update, FindOneAndUpdateOptions options);

    T findOneAndUpdate(ClientSession session, Document filter, Document update, FindOneAndUpdateOptions options);

    String createIndex(Document keys, IndexOptions options);

    ListIndexesIterable<Document> listIndexes();
}
