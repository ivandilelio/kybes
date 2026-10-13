package jakarta.persistence;
public @interface GeneratedValue { GenerationType strategy() default GenerationType.AUTO; }
