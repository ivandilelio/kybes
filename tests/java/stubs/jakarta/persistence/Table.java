package jakarta.persistence;
public @interface Table { String name() default ""; UniqueConstraint[] uniqueConstraints() default {}; Index[] indexes() default {}; }
