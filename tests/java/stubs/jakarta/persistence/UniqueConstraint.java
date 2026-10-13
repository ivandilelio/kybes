package jakarta.persistence;
public @interface UniqueConstraint { String name() default ""; String[] columnNames(); }
