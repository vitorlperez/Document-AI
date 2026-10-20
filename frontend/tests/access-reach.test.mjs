import assert from "node:assert/strict";
import test from "node:test";
import { adminWithoutSpacesWarning, reachSentence } from "../app/product/spaces-api.ts";

test("reach sentence names the documents and Spaces, or says the key reads nothing", () => {
  assert.equal(reachSentence({ spaces: ["RH", "Geral"], documents: 214 }), "Esta chave alcançará 214 documentos em: RH, Geral.");
  assert.equal(reachSentence({ spaces: [], documents: 0 }), "Esta chave não lerá nenhum documento: quem a criou não participa de nenhum Espaço.");
});

test("an admin without Spaces is warned before creating a key; members and admins with Spaces are not", () => {
  assert.match(adminWithoutSpacesWarning("admin", 0), /não lerá nenhum documento/);
  assert.match(adminWithoutSpacesWarning("owner", 0), /Entre em um Espaço/);
  assert.equal(adminWithoutSpacesWarning("admin", 1), null);
  assert.equal(adminWithoutSpacesWarning("admin", null), null, "unknown count never alarms");
});
