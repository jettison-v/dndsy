// Stylelint for askdnd's own CSS (foundations F4): the recommended rules, which catch mistakes (an unknown property or
// unit, a duplicated declaration, an invalid colour, an empty block), not style.
export default {
  extends: ["stylelint-config-recommended"],
  ignoreFiles: ["**/vendor/**", "**/node_modules/**"],
};
