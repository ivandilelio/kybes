package org.hibernate.cfg;
public class Configuration {
    public Configuration setProperty(String name, String value) { return this; }
    public Configuration addAnnotatedClass(Class<?> c) { return this; }
    public org.hibernate.SessionFactory buildSessionFactory() { throw new UnsupportedOperationException("stub"); }
}
