package jakarta.persistence;
public @interface JoinColumn { String name() default ""; boolean insertable() default true; boolean updatable() default true; }
