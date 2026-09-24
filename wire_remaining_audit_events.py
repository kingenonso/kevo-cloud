import ast

with open("app.py", "r") as f:
    content = f.read()

# 1. change_password
old_change_pw = '''    current_user.hashed_password = hash_password(request.new_password)
    db.commit()

    return {"message": "Password changed successfully"}'''

new_change_pw = '''    current_user.hashed_password = hash_password(request.new_password)
    current_user.tokens_valid_since = datetime.utcnow().replace(microsecond=0)
    log_audit_event(db, current_user.id, "password_changed", target_type="user", target_id=current_user.id)
    db.commit()

    return {"message": "Password changed successfully"}'''

assert content.count(old_change_pw) == 1, "change_password: match count != 1"
content = content.replace(old_change_pw, new_change_pw)

# 2. reset_password
old_reset_pw = '''    user.hashed_password = hash_password(request.new_password)
    reset_token.used_at = datetime.utcnow()
    db.commit()

    return {"message": "Password reset successfully"}'''

new_reset_pw = '''    user.hashed_password = hash_password(request.new_password)
    user.tokens_valid_since = datetime.utcnow().replace(microsecond=0)
    reset_token.used_at = datetime.utcnow()
    log_audit_event(db, user.id, "password_reset_completed", target_type="user", target_id=user.id)
    db.commit()

    return {"message": "Password reset successfully"}'''

assert content.count(old_reset_pw) == 1, "reset_password: match count != 1"
content = content.replace(old_reset_pw, new_reset_pw)

# 3. update_kyc_status
old_kyc = '''    user.kyc_status = status

    db.commit()
    db.refresh(user)'''

new_kyc = '''    old_status = user.kyc_status
    user.kyc_status = status

    log_audit_event(db, current_user.id, "kyc_status_changed", target_type="user", target_id=user.id, detail=f"{old_status} -> {status}")
    db.commit()
    db.refresh(user)'''

assert content.count(old_kyc) == 1, "update_kyc_status: match count != 1"
content = content.replace(old_kyc, new_kyc)

# 4. verify_evidence
old_evidence = '''    evidence.verification_status = status

    db.commit()
    db.refresh(evidence)'''

new_evidence = '''    evidence.verification_status = status

    log_audit_event(db, current_user.id, "evidence_" + status, target_type="evidence", target_id=evidence.id)
    db.commit()
    db.refresh(evidence)'''

assert content.count(old_evidence) == 1, "verify_evidence: match count != 1"
content = content.replace(old_evidence, new_evidence)

# 5. update_compliance_rule
old_rule = '''    for field, value in update_data.items():
        setattr(rule, field, value)

    db.commit()
    db.refresh(rule)'''

new_rule = '''    for field, value in update_data.items():
        setattr(rule, field, value)

    log_audit_event(db, current_user.id, "compliance_rule_updated", target_type="compliance_rule", target_id=rule.id, detail=", ".join(update_data.keys()))
    db.commit()
    db.refresh(rule)'''

assert content.count(old_rule) == 1, "update_compliance_rule: match count != 1"
content = content.replace(old_rule, new_rule)

ast.parse(content)

with open("app.py", "w") as f:
    f.write(content)

print("app.py updated: password_changed, password_reset_completed, kyc_status_changed, evidence_verified/rejected, compliance_rule_updated audit events added, syntax OK")
