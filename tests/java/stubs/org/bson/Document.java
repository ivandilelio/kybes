package org.bson;

/** Stub di compilazione: org.bson.Document. */
public final class Document extends java.util.LinkedHashMap<String, Object> {
    private static final long serialVersionUID = 1L;

    public Document() {
    }

    public Document(String key, Object value) {
        put(key, value);
    }

    public Document append(String key, Object value) {
        put(key, value);
        return this;
    }

    public static Document parse(String json) {
        return new Document("json", json);
    }

    public String toJson() {
        return "{}";
    }

    public String getString(String key) {
        return (String) get(key);
    }

    public Integer getInteger(String key) {
        return (Integer) get(key);
    }

    public <T> T get(String key, Class<T> cls) {
        return cls.cast(get(key));
    }
}
