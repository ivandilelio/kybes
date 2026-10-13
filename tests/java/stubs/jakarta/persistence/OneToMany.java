package jakarta.persistence;
public @interface OneToMany { String mappedBy() default ""; FetchType fetch() default FetchType.LAZY; }
