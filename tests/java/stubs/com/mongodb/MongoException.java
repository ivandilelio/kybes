package com.mongodb;

/** Stub di compilazione: com.mongodb.MongoException (il codice è conservato, come nel driver). */
public class MongoException extends RuntimeException {
    private static final long serialVersionUID = 1L;
    private final int code;

    public MongoException() { this(-3, null); }

    public MongoException(int code, String msg) {
        super(msg);
        this.code = code;
    }

    public int getCode() { return code; }
}
