package jakarta.persistence;
public @interface ManyToOne { FetchType fetch() default FetchType.EAGER; boolean optional() default true; }
