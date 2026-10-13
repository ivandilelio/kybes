package com.fasterxml.jackson.databind;
/** Stub delle firme di Jackson usate dal codice generato (solo compilazione). */
public abstract class JsonNode {
    public abstract JsonNode get(String field);
    public abstract boolean isNull();
    public abstract boolean isObject();
    public abstract String asText();
    public abstract int asInt();
    public abstract boolean asBoolean();
}
