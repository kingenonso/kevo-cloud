from sqlalchemy import Column, Integer, String, Numeric, ForeignKey
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(50), nullable=False, default="seller")

    listings = relationship("Listing", back_populates="seller")


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    company = Column(String(255), nullable=False)
    asset_type = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    asking_price = Column(Numeric(15, 2), nullable=False)

    seller = relationship("User", back_populates="listings")

class OwnershipRecord(Base):
    __tablename__ = "ownership_records"

    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    company = Column(String(255), nullable=False)
    asset_type = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    verification_status = Column(   
        String(50),
        nullable=False,
        default="pending"
    )
    verification_reference = Column(String(255), nullable=True)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)

    listing_id = Column(
        Integer,
        ForeignKey("listings.id"),
        nullable=False
    )

    buyer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    seller_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    quantity = Column(Integer, nullable=False)

    agreed_price = Column(
        Numeric(15, 2),
        nullable=False
    )

    status = Column(
        String(50),
        nullable=False,
        default="interested"
    )

class BuyerInterest(Base):
    __tablename__ = "buyer_interests"

    id = Column(Integer, primary_key=True)

    buyer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    company = Column(
        String(255),
        nullable=False
    )

    asset_type = Column(
        String(100),
        nullable=False
    )

    desired_quantity = Column(
        Integer,
        nullable=False
    )

    maximum_price = Column(
        Numeric(15, 2),
        nullable=False
    )

    status = Column(
        String(50),
        nullable=False,
        default="active"
    )    